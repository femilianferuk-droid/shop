import os
import logging
import tempfile
from pathlib import Path
import asyncio
from datetime import datetime
from dotenv import load_dotenv

from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    ReplyKeyboardMarkup, KeyboardButton, 
    InlineKeyboardMarkup, InlineKeyboardButton,
    FSInputFile
)
from aiogram.utils.keyboard import ReplyKeyboardBuilder, InlineKeyboardBuilder

import moviepy.editor as mp
import whisper
from googletrans import Translator as GoogleTranslator
from gtts import gTTS

# Загрузка переменных окружения
load_dotenv()

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Токен бота из переменных окружения
BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise ValueError("Не найден BOT_TOKEN в переменных окружения!")

# Инициализация
bot = Bot(token=BOT_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

# Загрузка модели Whisper (один раз при старте)
try:
    whisper_model = whisper.load_model("base")
    logger.info("Модель Whisper загружена успешно")
except Exception as e:
    logger.error(f"Ошибка загрузки Whisper: {e}")
    whisper_model = None

# Класс состояний FSM
class BotStates(StatesGroup):
    main_menu = State()
    video_mode = State()
    audio_to_text_mode = State()
    translate_mode = State()
    translate_lang_select = State()
    text_to_audio_mode = State()

# Языки для перевода
LANGUAGES = {
    '🇷🇺 Русский': 'ru',
    '🇬🇧 Английский': 'en',
    '🇩🇪 Немецкий': 'de',
    '🇫🇷 Французский': 'fr',
    '🇪🇸 Испанский': 'es',
    '🇮🇹 Итальянский': 'it',
    '🇨🇳 Китайский': 'zh-cn',
    '🇯🇵 Японский': 'ja',
    '🇰🇷 Корейский': 'ko',
    '🇦🇪 Арабский': 'ar'
}

# Клавиатуры
def get_main_keyboard():
    """Главное меню с 4 кнопками"""
    builder = ReplyKeyboardBuilder()
    builder.row(
        KeyboardButton(text="🎥 Видео в кружок"),
        KeyboardButton(text="🎤 Аудио в текст")
    )
    builder.row(
        KeyboardButton(text="🌐 Переводчик"),
        KeyboardButton(text="🔊 Текст в аудио")
    )
    return builder.as_markup(resize_keyboard=True)

def get_back_keyboard():
    """Клавиатура с кнопкой назад"""
    builder = ReplyKeyboardBuilder()
    builder.add(KeyboardButton(text="🔙 Назад в главное меню"))
    return builder.as_markup(resize_keyboard=True)

def get_languages_keyboard():
    """Инлайн клавиатура для выбора языка"""
    builder = InlineKeyboardBuilder()
    for lang_name, lang_code in LANGUAGES.items():
        builder.add(InlineKeyboardButton(
            text=lang_name,
            callback_data=f"lang_{lang_code}"
        ))
    # Располагаем кнопки в 2 столбца
    builder.adjust(2)
    return builder.as_markup()

# Обработчики команд
@dp.message(Command("start"))
async def cmd_start(message: types.Message, state: FSMContext):
    """Обработчик команды /start"""
    await state.set_state(BotStates.main_menu)
    await message.answer(
        "👋 Привет! Я многофункциональный бот, который поможет тебе:\n\n"
        "🎥 Конвертировать видео в кружок\n"
        "🎤 Превратить аудио в текст\n"
        "🌐 Перевести текст на любой язык\n"
        "🔊 Озвучить текст голосом\n\n"
        "Выбери нужную функцию в меню ниже:",
        reply_markup=get_main_keyboard()
    )

@dp.message(F.text == "🔙 Назад в главное меню")
async def back_to_main(message: types.Message, state: FSMContext):
    """Возврат в главное меню"""
    await state.set_state(BotStates.main_menu)
    await message.answer(
        "Главное меню. Выберите функцию:",
        reply_markup=get_main_keyboard()
    )

# 1. ВИДЕО В КРУЖОК
@dp.message(BotStates.main_menu, F.text == "🎥 Видео в кружок")
async def video_mode_start(message: types.Message, state: FSMContext):
    """Вход в режим конвертации видео в кружок"""
    await state.set_state(BotStates.video_mode)
    await message.answer(
        "📹 Отправь мне видео, и я превращу его в кружок!\n\n"
        "⚠️ Видео должно быть не длиннее 60 секунд",
        reply_markup=get_back_keyboard()
    )

@dp.message(BotStates.video_mode, F.video)
async def convert_to_video_note(message: types.Message, state: FSMContext):
    """Конвертация видео в кружок"""
    try:
        # Сообщение о начале обработки
        processing_msg = await message.answer("⏳ Обрабатываю видео, подожди немного...")
        
        # Скачиваем видео
        video_file = await bot.get_file(message.video.file_id)
        video_path = f"temp_video_{message.from_user.id}.mp4"
        await bot.download_file(video_file.file_path, video_path)
        
        # Проверка длительности
        with mp.VideoFileClip(video_path) as clip:
            duration = clip.duration
            if duration > 60:
                await message.answer(
                    "❌ Видео слишком длинное! Максимальная длина - 60 секунд.\n"
                    "Попробуй другое видео или обрежь это.",
                    reply_markup=get_back_keyboard()
                )
                os.remove(video_path)
                await processing_msg.delete()
                return
            
            # Обрезаем до квадрата
            min_size = min(clip.w, clip.h)
            cropped = clip.crop(
                x_center=clip.w/2,
                y_center=clip.h/2,
                width=min_size,
                height=min_size
            )
            
            # Сохраняем результат
            output_path = f"circle_{message.from_user.id}.mp4"
            cropped.write_videofile(
                output_path,
                codec='libx264',
                audio_codec='aac',
                temp_audiofile='temp-audio.m4a',
                remove_temp=True,
                fps=30,
                preset='medium',
                bitrate='1000k'
            )
        
        # Отправляем как видеосообщение
        video_note = FSInputFile(output_path)
        await message.answer_video_note(
            video_note,
            duration=int(duration),
            length=min_size
        )
        
        # Очистка
        os.remove(video_path)
        os.remove(output_path)
        await processing_msg.delete()
        
        logger.info(f"Пользователь {message.from_user.id} конвертировал видео в кружок")
        
    except Exception as e:
        logger.error(f"Ошибка при конвертации видео: {e}")
        await message.answer(
            "❌ Произошла ошибка при обработке видео. Попробуй другое видео.",
            reply_markup=get_back_keyboard()
        )

# 2. АУДИО В ТЕКСТ
@dp.message(BotStates.main_menu, F.text == "🎤 Аудио в текст")
async def audio_to_text_start(message: types.Message, state: FSMContext):
    """Вход в режим распознавания аудио"""
    await state.set_state(BotStates.audio_to_text_mode)
    await message.answer(
        "🎤 Отправь мне голосовое сообщение или аудиофайл, "
        "и я преобразую его в текст!",
        reply_markup=get_back_keyboard()
    )

@dp.message(BotStates.audio_to_text_mode, F.voice | F.audio)
async def audio_to_text_process(message: types.Message, state: FSMContext):
    """Распознавание аудио в текст"""
    if whisper_model is None:
        await message.answer(
            "❌ Модель распознавания не загружена. Попробуй позже.",
            reply_markup=get_back_keyboard()
        )
        return
    
    try:
        processing_msg = await message.answer("⏳ Распознаю речь, это может занять несколько секунд...")
        
        # Получаем файл
        if message.voice:
            file_id = message.voice.file_id
        else:
            file_id = message.audio.file_id
            
        audio_file = await bot.get_file(file_id)
        audio_path = f"temp_audio_{message.from_user.id}.ogg"
        await bot.download_file(audio_file.file_path, audio_path)
        
        # Конвертируем в формат, понятный Whisper
        import subprocess
        converted_path = f"converted_{message.from_user.id}.wav"
        subprocess.run([
            'ffmpeg', '-i', audio_path, 
            '-ar', '16000', '-ac', '1', '-c:a', 'pcm_s16le',
            converted_path, '-y'
        ], capture_output=True)
        
        # Распознаем текст
        result = whisper_model.transcribe(converted_path, language='ru')
        recognized_text = result["text"].strip()
        
        if recognized_text:
            await message.answer(
                f"📝 Распознанный текст:\n\n{recognized_text}",
                reply_markup=get_back_keyboard()
            )
            
            # Сохраняем в файл
            text_file_path = f"text_{message.from_user.id}.txt"
            with open(text_file_path, 'w', encoding='utf-8') as f:
                f.write(recognized_text)
            
            text_file = FSInputFile(text_file_path)
            await message.answer_document(
                text_file,
                caption="📄 Текст в файле"
            )
            os.remove(text_file_path)
        else:
            await message.answer(
                "❌ Не удалось распознать речь. Попробуй еще раз.",
                reply_markup=get_back_keyboard()
            )
        
        # Очистка
        os.remove(audio_path)
        os.remove(converted_path)
        await processing_msg.delete()
        
        logger.info(f"Пользователь {message.from_user.id} распознал аудио в текст")
        
    except Exception as e:
        logger.error(f"Ошибка при распознавании аудио: {e}")
        await message.answer(
            "❌ Произошла ошибка при распознавании. Попробуй другое аудио.",
            reply_markup=get_back_keyboard()
        )

# 3. ПЕРЕВОДЧИК
@dp.message(BotStates.main_menu, F.text == "🌐 Переводчик")
async def translate_start(message: types.Message, state: FSMContext):
    """Вход в режим перевода"""
    await state.set_state(BotStates.translate_lang_select)
    await message.answer(
        "🌐 Выбери язык, на который нужно перевести:",
        reply_markup=get_languages_keyboard()
    )

@dp.callback_query(StateFilter(BotStates.translate_lang_select), F.data.startswith("lang_"))
async def select_language(callback: types.CallbackQuery, state: FSMContext):
    """Выбор языка для перевода"""
    lang_code = callback.data.replace("lang_", "")
    
    # Находим название языка по коду
    lang_name = "неизвестный язык"
    for name, code in LANGUAGES.items():
        if code == lang_code:
            lang_name = name
            break
    
    await state.update_data(target_lang=lang_code, target_lang_name=lang_name)
    await state.set_state(BotStates.translate_mode)
    
    await callback.message.edit_text(
        f"✅ Выбран язык: {lang_name}\n\n"
        "📝 Отправь текст, который нужно перевести:"
    )
    await callback.answer()

@dp.message(BotStates.translate_mode)
async def translate_text(message: types.Message, state: FSMContext):
    """Перевод текста"""
    try:
        user_data = await state.get_data()
        target_lang = user_data.get('target_lang', 'en')
        target_lang_name = user_data.get('target_lang_name', 'Английский')
        
        if len(message.text) > 5000:
            await message.answer(
                "❌ Текст слишком длинный! Максимум 5000 символов.",
                reply_markup=get_back_keyboard()
            )
            return
        
        processing_msg = await message.answer("⏳ Перевожу...")
        
        translator = GoogleTranslator()
        translated = translator.translate(message.text, dest=target_lang)
        
        result_text = (
            f"🔤 Оригинал ({translated.src}):\n{message.text}\n\n"
            f"✅ Перевод ({target_lang_name}):\n{translated.text}"
        )
        
        await message.answer(result_text, reply_markup=get_back_keyboard())
        await processing_msg.delete()
        
        logger.info(f"Пользователь {message.from_user.id} перевел текст")
        
    except Exception as e:
        logger.error(f"Ошибка при переводе: {e}")
        await message.answer(
            "❌ Ошибка при переводе. Попробуй другой текст.",
            reply_markup=get_back_keyboard()
        )

# 4. ТЕКСТ В АУДИО
@dp.message(BotStates.main_menu, F.text == "🔊 Текст в аудио")
async def text_to_audio_start(message: types.Message, state: FSMContext):
    """Вход в режим озвучки текста"""
    await state.set_state(BotStates.text_to_audio_mode)
    await message.answer(
        "🔊 Отправь текст (до 3000 символов), и я озвучу его голосом!",
        reply_markup=get_back_keyboard()
    )

@dp.message(BotStates.text_to_audio_mode)
async def text_to_audio_process(message: types.Message, state: FSMContext):
    """Озвучка текста"""
    try:
        text = message.text
        
        if len(text) > 3000:
            await message.answer(
                "❌ Текст слишком длинный! Максимум 3000 символов.\n"
                "Попробуй отправить текст покороче.",
                reply_markup=get_back_keyboard()
            )
            return
        
        processing_msg = await message.answer("⏳ Создаю аудиофайл...")
        
        # Создаем аудио
        audio_path = f"tts_{message.from_user.id}.ogg"
        tts = gTTS(text=text, lang='ru', slow=False)
        tts.save(audio_path)
        
        # Отправляем как голосовое сообщение
        audio_file = FSInputFile(audio_path)
        await message.answer_voice(
            audio_file,
            caption="🎧 Готово!"
        )
        
        # Очистка
        os.remove(audio_path)
        await processing_msg.delete()
        
        logger.info(f"Пользователь {message.from_user.id} создал аудио из текста")
        
    except Exception as e:
        logger.error(f"Ошибка при создании аудио: {e}")
        await message.answer(
            "❌ Ошибка при создании аудио. Попробуй другой текст.",
            reply_markup=get_back_keyboard()
        )

# Обработка некорректных сообщений
@dp.message(BotStates.video_mode)
async def incorrect_video_message(message: types.Message):
    """Неверный формат в режиме видео"""
    await message.answer(
        "❌ Пожалуйста, отправь видеофайл.\n"
        "Или нажми '🔙 Назад' для возврата в меню.",
        reply_markup=get_back_keyboard()
    )

@dp.message(BotStates.audio_to_text_mode)
async def incorrect_audio_message(message: types.Message):
    """Неверный формат в режиме аудио"""
    await message.answer(
        "❌ Пожалуйста, отправь голосовое сообщение или аудиофайл.\n"
        "Или нажми '🔙 Назад' для возврата в меню.",
        reply_markup=get_back_keyboard()
    )

@dp.message()
async def unknown_message(message: types.Message):
    """Обработка неизвестных сообщений"""
    await message.answer(
        "Я не понял команду. Пожалуйста, воспользуйся меню.",
        reply_markup=get_main_keyboard()
    )

# Запуск бота
async def main():
    logger.info("Запуск бота...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
