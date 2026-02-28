import os
import sqlite3
import asyncio
from datetime import datetime
from typing import List, Dict, Optional, Tuple
from contextlib import closing

from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command, CommandStart
from aiogram.types import (
    Message, CallbackQuery, ReplyKeyboardMarkup, KeyboardButton,
    InlineKeyboardMarkup, InlineKeyboardButton, FSInputFile
)
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from dotenv import load_dotenv

# Загружаем переменные окружения
load_dotenv()

# Конфигурация
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID", "797398817"))
SUPPORT_USERNAME = os.getenv("SUPPORT_USERNAME", "MonkeyShopSupport")

if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN не найден в переменных окружения!")

# Инициализация бота и диспетчера
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

# ==================== БАЗА ДАННЫХ ====================
class Database:
    def __init__(self):
        self.conn = sqlite3.connect('monkey_shop.db', check_same_thread=False)
        self.cursor = self.conn.cursor()
        self.create_tables()
    
    def create_tables(self):
        # Таблица пользователей
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                last_name TEXT,
                registered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # Таблица категорий
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS categories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE,
                emoji TEXT
            )
        ''')
        
        # Таблица товаров
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS products (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                category_id INTEGER,
                name TEXT,
                description TEXT,
                price INTEGER,
                quantity INTEGER,
                FOREIGN KEY (category_id) REFERENCES categories (id)
            )
        ''')
        
        # Таблица настроек
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT
            )
        ''')
        
        self.conn.commit()
        
        # Добавляем категории по умолчанию
        self.init_categories()
        
        # Добавляем ссылку на политику по умолчанию
        self.init_settings()
        
        # Добавляем тестовые товары (если база пустая)
        self.add_test_products()
    
    def init_categories(self):
        categories = [
            ("Telegram аккаунты", "📱"),
            ("Telegram каналы", "💬"),
            ("Telegram группы", "👥"),
            ("Telegram боты", "🤖"),
            ("Домены для сайтов", "🌐")
        ]
        
        for name, emoji in categories:
            try:
                self.cursor.execute(
                    "INSERT INTO categories (name, emoji) VALUES (?, ?)",
                    (name, emoji)
                )
            except sqlite3.IntegrityError:
                pass
        self.conn.commit()
    
    def init_settings(self):
        default_settings = [
            ("privacy_policy", "https://example.com/privacy")
        ]
        
        for key, value in default_settings:
            self.cursor.execute(
                "INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)",
                (key, value)
            )
        self.conn.commit()
    
    def add_test_products(self):
        # Проверяем, есть ли товары
        self.cursor.execute("SELECT COUNT(*) FROM products")
        count = self.cursor.fetchone()[0]
        
        if count == 0:
            # Получаем ID категории "Telegram аккаунты"
            self.cursor.execute("SELECT id FROM categories WHERE name = ?", ("Telegram аккаунты",))
            cat_id = self.cursor.fetchone()[0]
            
            # Добавляем тестовые товары
            test_products = [
                (cat_id, "Аккаунт USA (5 шт.)", "Аккаунт США, отличное качество", 100, 10),
                (cat_id, "Аккаунт RU (2 шт.)", "Аккаунт Россия, премиум качество", 150, 5)
            ]
            
            self.cursor.executemany(
                "INSERT INTO products (category_id, name, description, price, quantity) VALUES (?, ?, ?, ?, ?)",
                test_products
            )
            self.conn.commit()
    
    # Работа с пользователями
    def add_user(self, user_id: int, username: str, first_name: str, last_name: str = ""):
        self.cursor.execute(
            "INSERT OR IGNORE INTO users (user_id, username, first_name, last_name) VALUES (?, ?, ?, ?)",
            (user_id, username, first_name, last_name)
        )
        self.conn.commit()
    
    def get_all_users(self) -> List[int]:
        self.cursor.execute("SELECT user_id FROM users")
        return [row[0] for row in self.cursor.fetchall()]
    
    def get_users_count(self) -> int:
        self.cursor.execute("SELECT COUNT(*) FROM users")
        return self.cursor.fetchone()[0]
    
    # Работа с категориями
    def get_categories(self) -> List[Tuple[int, str, str]]:
        self.cursor.execute("SELECT id, name, emoji FROM categories")
        return self.cursor.fetchall()
    
    # Работа с товарами
    def get_products_by_category(self, category_id: int) -> List[Tuple[int, str, int, int]]:
        self.cursor.execute(
            "SELECT id, name, price, quantity FROM products WHERE category_id = ? AND quantity > 0",
            (category_id,)
        )
        return self.cursor.fetchall()
    
    def get_product(self, product_id: int) -> Optional[Tuple]:
        self.cursor.execute(
            "SELECT id, name, description, price, quantity FROM products WHERE id = ?",
            (product_id,)
        )
        return self.cursor.fetchone()
    
    def add_product(self, category_id: int, name: str, description: str, price: int, quantity: int):
        self.cursor.execute(
            "INSERT INTO products (category_id, name, description, price, quantity) VALUES (?, ?, ?, ?, ?)",
            (category_id, name, description, price, quantity)
        )
        self.conn.commit()
        return self.cursor.lastrowid
    
    def get_products_count(self) -> int:
        self.cursor.execute("SELECT COUNT(*) FROM products")
        return self.cursor.fetchone()[0]
    
    # Работа с настройками
    def get_setting(self, key: str) -> str:
        self.cursor.execute("SELECT value FROM settings WHERE key = ?", (key,))
        result = self.cursor.fetchone()
        return result[0] if result else ""
    
    def update_setting(self, key: str, value: str):
        self.cursor.execute(
            "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
            (key, value)
        )
        self.conn.commit()
    
    def __del__(self):
        self.conn.close()

# Создаем экземпляр базы данных
db = Database()

# ==================== FSM СОСТОЯНИЯ ====================
class AddProductStates(StatesGroup):
    category = State()
    name = State()
    description = State()
    price = State()
    quantity = State()

class MailingStates(StatesGroup):
    text = State()

class ChangePolicyStates(StatesGroup):
    new_link = State()

# ==================== КЛАВИАТУРЫ ====================
def get_main_keyboard() -> ReplyKeyboardMarkup:
    """Главное меню (Reply Keyboard)"""
    keyboard = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="Купить товар 🛍️")],
            [KeyboardButton(text="Профиль 👤")],
            [KeyboardButton(text="О нас ℹ️")]
        ],
        resize_keyboard=True
    )
    return keyboard

def get_admin_keyboard() -> ReplyKeyboardMarkup:
    """Админ-панель (Reply Keyboard)"""
    keyboard = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="Статистика 📊")],
            [KeyboardButton(text="Рассылка 📨")],
            [KeyboardButton(text="Добавление товаров ➕")],
            [KeyboardButton(text="Изменение ссылки на политику 🔗")],
            [KeyboardButton(text="Выйти из админки 🚪")]
        ],
        resize_keyboard=True
    )
    return keyboard

def get_categories_inline() -> InlineKeyboardMarkup:
    """Инлайн клавиатура с категориями"""
    categories = db.get_categories()
    buttons = []
    for cat_id, name, emoji in categories:
        buttons.append([InlineKeyboardButton(
            text=f"{emoji} {name}",
            callback_data=f"category_{cat_id}"
        )])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def get_products_inline(category_id: int) -> InlineKeyboardMarkup:
    """Инлайн клавиатура с товарами категории"""
    products = db.get_products_by_category(category_id)
    buttons = []
    for prod_id, name, price, quantity in products:
        buttons.append([InlineKeyboardButton(
            text=f"{name} — {price} руб. (в наличии: {quantity})",
            callback_data=f"product_{prod_id}"
        )])
    buttons.append([InlineKeyboardButton(
        text="🔙 Назад к категориям",
        callback_data="back_to_categories"
    )])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def get_product_actions_inline(product_id: int) -> InlineKeyboardMarkup:
    """Инлайн клавиатура для действий с товаром"""
    buttons = [
        [InlineKeyboardButton(
            text="💰 Купить",
            callback_data=f"buy_{product_id}"
        )],
        [InlineKeyboardButton(
            text="🔙 Назад к товарам",
            callback_data="back_to_products"
        )]
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)

# ==================== ОБРАБОТЧИКИ КОМАНД ====================
@dp.message(CommandStart())
async def cmd_start(message: Message):
    """Обработчик команды /start"""
    user = message.from_user
    db.add_user(
        user_id=user.id,
        username=user.username or "",
        first_name=user.first_name or "",
        last_name=user.last_name or ""
    )
    
    await message.answer(
        f"👋 Добро пожаловать в Monkey Shop!\n\n"
        f"Здесь вы можете приобрести различные цифровые товары: "
        f"аккаунты, каналы, группы, боты и домены.",
        reply_markup=get_main_keyboard()
    )

@dp.message(Command("admin"))
async def cmd_admin(message: Message):
    """Вход в админ-панель"""
    if message.from_user.id != ADMIN_ID:
        await message.answer("⛔ У вас нет доступа к админ-панели.")
        return
    
    await message.answer(
        "👨‍💼 Добро пожаловать в админ-панель!",
        reply_markup=get_admin_keyboard()
    )

# ==================== ОБРАБОТЧИКИ ГЛАВНОГО МЕНЮ ====================
@dp.message(F.text == "Купить товар 🛍️")
async def buy_product(message: Message):
    """Раздел покупки товаров"""
    await message.answer(
        "🛍️ Выберите категорию товара:",
        reply_markup=get_categories_inline()
    )

@dp.message(F.text == "Профиль 👤")
async def profile(message: Message):
    """Раздел профиля пользователя"""
    user = message.from_user
    username = f"@{user.username}" if user.username else "не указан"
    
    await message.answer(
        f"👤 Ваш профиль:\n\n"
        f"• Имя: {user.first_name} {user.last_name or ''}\n"
        f"• ID: <code>{user.id}</code>\n"
        f"• Username: {username}",
        parse_mode="HTML"
    )

@dp.message(F.text == "О нас ℹ️")
async def about(message: Message):
    """Раздел информации о магазине"""
    policy_link = db.get_setting("privacy_policy")
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="📜 Политика конфиденциальности",
            url=policy_link
        )]
    ])
    
    await message.answer(
        "🛍️ Monkey Shop - ваш надежный магазин цифровых товаров!\n\n"
        "Мы предлагаем:\n"
        "• Telegram аккаунты\n"
        "• Telegram каналы\n"
        "• Telegram группы\n"
        "• Telegram боты\n"
        "• Домены для сайтов\n\n"
        "Все товары проходят проверку качества. По всем вопросам обращайтесь в поддержку.",
        reply_markup=keyboard
    )

# ==================== ОБРАБОТЧИКИ ИНЛАЙН КНОПОК ====================
@dp.callback_query(F.data.startswith("category_"))
async def show_products(callback: CallbackQuery):
    """Показать товары категории"""
    category_id = int(callback.data.split("_")[1])
    await callback.message.edit_text(
        "📦 Выберите товар:",
        reply_markup=get_products_inline(category_id)
    )
    await callback.answer()

@dp.callback_query(F.data.startswith("product_"))
async def show_product(callback: CallbackQuery):
    """Показать детали товара"""
    product_id = int(callback.data.split("_")[1])
    product = db.get_product(product_id)
    
    if not product:
        await callback.message.edit_text("❌ Товар не найден")
        await callback.answer()
        return
    
    prod_id, name, description, price, quantity = product
    
    await callback.message.edit_text(
        f"📄 <b>{name}</b>\n\n"
        f"{description}\n\n"
        f"💰 Цена: {price} руб.\n"
        f"📦 В наличии: {quantity} шт.",
        parse_mode="HTML",
        reply_markup=get_product_actions_inline(product_id)
    )
    await callback.answer()

@dp.callback_query(F.data.startswith("buy_"))
async def buy_product_action(callback: CallbackQuery):
    """Обработка покупки товара"""
    product_id = int(callback.data.split("_")[1])
    product = db.get_product(product_id)
    
    if not product:
        await callback.message.edit_text("❌ Товар не найден")
        await callback.answer()
        return
    
    name = product[1]
    
    await callback.message.edit_text(
        f"✅ Для покупки товара \"{name}\", пожалуйста, свяжитесь с поддержкой:\n\n"
        f"📱 @{SUPPORT_USERNAME}",
        reply_markup=None
    )
    await callback.answer()

@dp.callback_query(F.data == "back_to_categories")
async def back_to_categories(callback: CallbackQuery):
    """Назад к списку категорий"""
    await callback.message.edit_text(
        "🛍️ Выберите категорию товара:",
        reply_markup=get_categories_inline()
    )
    await callback.answer()

@dp.callback_query(F.data == "back_to_products")
async def back_to_products(callback: CallbackQuery):
    """Назад к списку товаров (сохраняем контекст)"""
    # Извлекаем category_id из предыдущего сообщения
    await callback.message.edit_text(
        "📦 Выберите товар:",
        reply_markup=get_categories_inline()  # Временно возвращаем к категориям
    )
    await callback.answer()

# ==================== АДМИН-ПАНЕЛЬ ====================
@dp.message(F.text == "Статистика 📊")
async def admin_stats(message: Message):
    """Просмотр статистики"""
    if message.from_user.id != ADMIN_ID:
        return
    
    users_count = db.get_users_count()
    products_count = db.get_products_count()
    
    await message.answer(
        f"📊 Статистика бота:\n\n"
        f"👥 Пользователей: {users_count}\n"
        f"📦 Товаров в базе: {products_count}"
    )

@dp.message(F.text == "Рассылка 📨")
async def admin_mailing(message: Message, state: FSMContext):
    """Начало рассылки"""
    if message.from_user.id != ADMIN_ID:
        return
    
    await message.answer(
        "📨 Отправьте текст для рассылки всем пользователям:"
    )
    await state.set_state(MailingStates.text)

@dp.message(MailingStates.text)
async def process_mailing(message: Message, state: FSMContext):
    """Обработка текста рассылки"""
    if message.from_user.id != ADMIN_ID:
        return
    
    text = message.text
    users = db.get_all_users()
    
    await message.answer(f"📨 Начинаю рассылку {len(users)} пользователям...")
    
    success = 0
    failed = 0
    
    for user_id in users:
        try:
            await bot.send_message(user_id, text)
            success += 1
            await asyncio.sleep(0.05)  # Небольшая задержка чтобы не спамить
        except:
            failed += 1
    
    await message.answer(
        f"✅ Рассылка завершена!\n\n"
        f"• Успешно: {success}\n"
        f"• Не удалось: {failed}"
    )
    await state.clear()

@dp.message(F.text == "Добавление товаров ➕")
async def admin_add_product(message: Message, state: FSMContext):
    """Начало добавления товара"""
    if message.from_user.id != ADMIN_ID:
        return
    
    categories = db.get_categories()
    cats_text = "\n".join([f"{emoji} {name}" for _, name, emoji in categories])
    
    await message.answer(
        f"📦 Добавление нового товара\n\n"
        f"Выберите категорию (отправьте название):\n\n{cats_text}"
    )
    await state.set_state(AddProductStates.category)

@dp.message(AddProductStates.category)
async def process_product_category(message: Message, state: FSMContext):
    """Обработка категории товара"""
    if message.from_user.id != ADMIN_ID:
        return
    
    category_name = message.text
    # Убираем эмодзи из названия если есть
    for emoji in ["📱", "💬", "👥", "🤖", "🌐"]:
        category_name = category_name.replace(emoji, "").strip()
    
    # Ищем категорию
    db.cursor.execute("SELECT id FROM categories WHERE name LIKE ?", (f"%{category_name}%",))
    category = db.cursor.fetchone()
    
    if not category:
        await message.answer("❌ Категория не найдена. Попробуйте еще раз:")
        return
    
    await state.update_data(category_id=category[0])
    await message.answer("Введите название товара:")
    await state.set_state(AddProductStates.name)

@dp.message(AddProductStates.name)
async def process_product_name(message: Message, state: FSMContext):
    """Обработка названия товара"""
    if message.from_user.id != ADMIN_ID:
        return
    
    await state.update_data(name=message.text)
    await message.answer("Введите описание товара:")
    await state.set_state(AddProductStates.description)

@dp.message(AddProductStates.description)
async def process_product_description(message: Message, state: FSMContext):
    """Обработка описания товара"""
    if message.from_user.id != ADMIN_ID:
        return
    
    await state.update_data(description=message.text)
    await message.answer("Введите цену товара (только число):")
    await state.set_state(AddProductStates.price)

@dp.message(AddProductStates.price)
async def process_product_price(message: Message, state: FSMContext):
    """Обработка цены товара"""
    if message.from_user.id != ADMIN_ID:
        return
    
    try:
        price = int(message.text)
        if price <= 0:
            raise ValueError
    except:
        await message.answer("❌ Пожалуйста, введите положительное число:")
        return
    
    await state.update_data(price=price)
    await message.answer("Введите количество товара в наличии (только число):")
    await state.set_state(AddProductStates.quantity)

@dp.message(AddProductStates.quantity)
async def process_product_quantity(message: Message, state: FSMContext):
    """Обработка количества товара и сохранение"""
    if message.from_user.id != ADMIN_ID:
        return
    
    try:
        quantity = int(message.text)
        if quantity < 0:
            raise ValueError
    except:
        await message.answer("❌ Пожалуйста, введите неотрицательное число:")
        return
    
    data = await state.get_data()
    
    product_id = db.add_product(
        category_id=data['category_id'],
        name=data['name'],
        description=data['description'],
        price=data['price'],
        quantity=quantity
    )
    
    await message.answer(
        f"✅ Товар успешно добавлен!\n\n"
        f"ID: {product_id}\n"
        f"Название: {data['name']}\n"
        f"Цена: {data['price']} руб.\n"
        f"Количество: {quantity}"
    )
    await state.clear()

@dp.message(F.text == "Изменение ссылки на политику 🔗")
async def admin_change_policy(message: Message, state: FSMContext):
    """Изменение ссылки на политику конфиденциальности"""
    if message.from_user.id != ADMIN_ID:
        return
    
    current_link = db.get_setting("privacy_policy")
    
    await message.answer(
        f"🔗 Текущая ссылка на политику конфиденциальности:\n"
        f"{current_link}\n\n"
        f"Отправьте новую ссылку:"
    )
    await state.set_state(ChangePolicyStates.new_link)

@dp.message(ChangePolicyStates.new_link)
async def process_new_policy(message: Message, state: FSMContext):
    """Сохранение новой ссылки"""
    if message.from_user.id != ADMIN_ID:
        return
    
    new_link = message.text
    db.update_setting("privacy_policy", new_link)
    
    await message.answer(f"✅ Ссылка успешно обновлена!\n\nНовая ссылка: {new_link}")
    await state.clear()

@dp.message(F.text == "Выйти из админки 🚪")
async def admin_exit(message: Message):
    """Выход из админ-панели"""
    if message.from_user.id != ADMIN_ID:
        return
    
    await message.answer(
        "👋 Вы вышли из админ-панели",
        reply_markup=get_main_keyboard()
    )

# ==================== ЗАПУСК БОТА ====================
async def main():
    print(f"Бот запущен! Админ ID: {ADMIN_ID}")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
