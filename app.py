import sqlite3
import uuid
import os
from datetime import datetime
from flask import Flask, render_template, request, jsonify
import telebot
import threading

# ================== إعدادات البوت ==================
BOT_TOKEN = "8901433681:AAGnY6CGkqx03AnM7PcRjooFi-J7lDby3Z8"
OWNER_ID = 7750222393

# ================== إعدادات Flask ==================
app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = 'static/uploads'
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

# ================== قاعدة البيانات ==================
def get_db():
    conn = sqlite3.connect('store.db')
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS products (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            description TEXT,
            price REAL NOT NULL,
            stock INTEGER DEFAULT 999,
            image_path TEXT,
            created_at TEXT
        )
    ''')
    try:
        c.execute('ALTER TABLE products ADD COLUMN image_path TEXT')
    except:
        pass
    c.execute('''
        CREATE TABLE IF NOT EXISTS orders (
            id TEXT PRIMARY KEY,
            product_id TEXT,
            customer_name TEXT NOT NULL,
            customer_username TEXT NOT NULL,
            payment_status TEXT DEFAULT 'pending',
            created_at TEXT
        )
    ''')
    c.execute('''
        CREATE TABLE IF NOT EXISTS authorized_users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT UNIQUE NOT NULL,
            granted_by TEXT,
            granted_at TEXT
        )
    ''')
    conn.commit()
    conn.close()

init_db()

# ================== صفحات الموقع ==================
@app.route('/')
def home():
    return render_template('index.html')

@app.route('/shop')
def shop():
    conn = get_db()
    products = conn.execute('SELECT * FROM products').fetchall()
    conn.close()
    return render_template('shop.html', products=products)

@app.route('/product/<product_id>')
def product_detail(product_id):
    conn = get_db()
    p = conn.execute('SELECT * FROM products WHERE id = ?', (product_id,)).fetchone()
    conn.close()
    if not p:
        return "منتج غير موجود", 404
    return render_template('product.html', product=p)

@app.route('/api/products', methods=['GET'])
def get_products():
    conn = get_db()
    products = conn.execute('SELECT * FROM products').fetchall()
    conn.close()
    return jsonify([dict(p) for p in products])

@app.route('/api/orders', methods=['POST'])
def create_order():
    data = request.get_json()
    conn = get_db()
    product = conn.execute('SELECT * FROM products WHERE id = ?', (data.get('product_id'),)).fetchone()
    if not product:
        conn.close()
        return jsonify({'error': 'منتج غير موجود'}), 404
    order_id = str(uuid.uuid4())
    conn.execute('''
        INSERT INTO orders (id, product_id, customer_name, customer_username, created_at)
        VALUES (?, ?, ?, ?, ?)
    ''', (order_id, product['id'], data.get('customer_name'), data.get('customer_username'), datetime.utcnow().isoformat()))
    conn.commit()
    conn.close()
    try:
        bot.send_message(OWNER_ID, f"🛒 طلب جديد!\n👤 {data.get('customer_name')}\n📱 @{data.get('customer_username')}\n📦 {product['name']}\n💰 {int(product['price'])}$")
    except:
        pass
    return jsonify({'order_id': order_id, 'message': 'تم إنشاء الطلب'}), 201

# ================== بوت تيليجرام ==================
bot = telebot.TeleBot(BOT_TOKEN)
user_state = {}

def is_authorized(user_id):
    if user_id == OWNER_ID:
        return True
    conn = get_db()
    user = conn.execute('SELECT * FROM authorized_users WHERE user_id = ?', (str(user_id),)).fetchone()
    conn.close()
    return user is not None

def find_product_by_partial_id(partial_id):
    conn = get_db()
    product = conn.execute('SELECT * FROM products WHERE id LIKE ?', (partial_id + '%',)).fetchone()
    conn.close()
    return product

def main_keyboard():
    keyboard = telebot.types.ReplyKeyboardMarkup(row_width=2, resize_keyboard=True)
    keyboard.add(
        telebot.types.KeyboardButton("📦 قائمة المنتجات"),
        telebot.types.KeyboardButton("➕ إضافة منتج")
    )
    keyboard.add(
        telebot.types.KeyboardButton("✏️ تعديل منتج"),
        telebot.types.KeyboardButton("🗑️ حذف منتج")
    )
    keyboard.add(
        telebot.types.KeyboardButton("📋 الطلبات"),
        telebot.types.KeyboardButton("👥 المستخدمين")
    )
    keyboard.add(
        telebot.types.KeyboardButton("🔑 منح صلاحية"),
        telebot.types.KeyboardButton("❌ إلغاء العملية")
    )
    return keyboard

def cancel_operation(message):
    if message.from_user.id in user_state:
        del user_state[message.from_user.id]
    bot.reply_to(message, "❌ تم إلغاء العملية.", reply_markup=main_keyboard())

# ================== أوامر البوت ==================
@bot.message_handler(commands=['start'])
def start(message):
    if not is_authorized(message.from_user.id):
        bot.reply_to(message, "⛔ غير مصرح لك.")
        return
    bot.reply_to(message, "🔥 مرحباً بك في لوحة التحكم!", reply_markup=main_keyboard())

# ================== قائمة المنتجات ==================
@bot.message_handler(func=lambda message: message.text == "📦 قائمة المنتجات")
def list_products_button(message):
    if not is_authorized(message.from_user.id): return
    conn = get_db()
    products = conn.execute('SELECT * FROM products').fetchall()
    conn.close()
    if not products:
        bot.reply_to(message, "📭 لا توجد منتجات.")
        return
    msg = "📦 *المنتجات:*\n"
    for p in products:
        msg += f"\n🆔 `{p['id'][:8]}` | *{p['name']}* | 💰 {int(p['price'])}$"
    bot.reply_to(message, msg, parse_mode='Markdown')

# ================== إضافة منتج (خطوات واضحة) ==================
@bot.message_handler(func=lambda message: message.text == "➕ إضافة منتج")
def add_product_button(message):
    if not is_authorized(message.from_user.id): return
    user_state[message.from_user.id] = {'step': 'add_name'}
    bot.reply_to(message, "📝 أرسل *اسم* المنتج:", parse_mode='Markdown')

@bot.message_handler(func=lambda message: message.from_user.id in user_state and user_state[message.from_user.id].get('step') == 'add_name')
def add_name(message):
    if not is_authorized(message.from_user.id): return
    user_state[message.from_user.id]['name'] = message.text
    user_state[message.from_user.id]['step'] = 'add_description'
    bot.reply_to(message, "📝 أرسل *وصف* المنتج:", parse_mode='Markdown')

@bot.message_handler(func=lambda message: message.from_user.id in user_state and user_state[message.from_user.id].get('step') == 'add_description')
def add_description(message):
    if not is_authorized(message.from_user.id): return
    user_state[message.from_user.id]['description'] = message.text
    user_state[message.from_user.id]['step'] = 'add_price'
    bot.reply_to(message, "💰 أرسل *سعر* المنتج (رقم فقط):", parse_mode='Markdown')

@bot.message_handler(func=lambda message: message.from_user.id in user_state and user_state[message.from_user.id].get('step') == 'add_price')
def add_price(message):
    if not is_authorized(message.from_user.id): return
    try:
        price = float(message.text)
        user_state[message.from_user.id]['price'] = price
        user_state[message.from_user.id]['step'] = 'add_image'
        bot.reply_to(message, "🖼️ أرسل *صورة* المنتج (اضغط على 📎):", parse_mode='Markdown')
    except:
        bot.reply_to(message, "❌ السعر يجب أن يكون *رقم*. جرب مرة أخرى:", parse_mode='Markdown')

@bot.message_handler(content_types=['photo'], func=lambda message: message.from_user.id in user_state and user_state[message.from_user.id].get('step') == 'add_image')
def add_image(message):
    if not is_authorized(message.from_user.id): return
    try:
        file_info = bot.get_file(message.photo[-1].file_id)
        file_name = f"{uuid.uuid4()}.jpg"
        file_path = os.path.join(app.config['UPLOAD_FOLDER'], file_name)
        downloaded_file = bot.download_file(file_info.file_path)
        with open(file_path, 'wb') as f:
            f.write(downloaded_file)
        conn = get_db()
        product_id = str(uuid.uuid4())
        conn.execute('''
            INSERT INTO products (id, name, description, price, image_path, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (product_id,
              user_state[message.from_user.id]['name'],
              user_state[message.from_user.id]['description'],
              user_state[message.from_user.id]['price'],
              file_path,
              datetime.utcnow().isoformat()))
        conn.commit()
        conn.close()
        bot.reply_to(message, f"✅ تم إضافة المنتج *{user_state[message.from_user.id]['name']}* بنجاح!", reply_markup=main_keyboard(), parse_mode='Markdown')
        del user_state[message.from_user.id]
    except Exception as e:
        bot.reply_to(message, f"❌ حدث خطأ: {e}")

# ================== تعديل منتج ==================
@bot.message_handler(func=lambda message: message.text == "✏️ تعديل منتج")
def edit_product_button(message):
    if not is_authorized(message.from_user.id): return
    user_state[message.from_user.id] = {'step': 'edit_id'}
    bot.reply_to(message, "📝 أرسل *ID* المنتج (أول 8 حروف أو كامل):", parse_mode='Markdown')

@bot.message_handler(func=lambda message: message.from_user.id in user_state and user_state[message.from_user.id].get('step') == 'edit_id')
def edit_id(message):
    if not is_authorized(message.from_user.id): return
    product = find_product_by_partial_id(message.text.strip())
    if not product:
        bot.reply_to(message, "❌ منتج غير موجود. تأكد من ID (استخدم /list).")
        del user_state[message.from_user.id]
        return
    user_state[message.from_user.id]['product_id'] = product['id']
    user_state[message.from_user.id]['step'] = 'edit_field'
    keyboard = telebot.types.ReplyKeyboardMarkup(row_width=2, resize_keyboard=True)
    keyboard.add(
        telebot.types.KeyboardButton("💰 تعديل السعر"),
        telebot.types.KeyboardButton("📝 تعديل الوصف")
    )
    keyboard.add(
        telebot.types.KeyboardButton("❌ إلغاء العملية")
    )
    bot.reply_to(message, f"✏️ تعديل المنتج: *{product['name']}*\nاختر ما تريد تعديله:", reply_markup=keyboard, parse_mode='Markdown')

@bot.message_handler(func=lambda message: message.from_user.id in user_state and user_state[message.from_user.id].get('step') == 'edit_field')
def edit_field(message):
    if not is_authorized(message.from_user.id): return
    if message.text == "💰 تعديل السعر":
        user_state[message.from_user.id]['step'] = 'edit_price'
        bot.reply_to(message, "💰 أرسل *السعر الجديد* (رقم فقط):", parse_mode='Markdown')
    elif message.text == "📝 تعديل الوصف":
        user_state[message.from_user.id]['step'] = 'edit_description'
        bot.reply_to(message, "📝 أرسل *الوصف الجديد*:", parse_mode='Markdown')
    elif message.text == "❌ إلغاء العملية":
        cancel_operation(message)
    else:
        bot.reply_to(message, "❌ استخدم الأزرار للاختيار.")

@bot.message_handler(func=lambda message: message.from_user.id in user_state and user_state[message.from_user.id].get('step') == 'edit_price')
def edit_price(message):
    if not is_authorized(message.from_user.id): return
    try:
        new_price = float(message.text)
        conn = get_db()
        conn.execute('UPDATE products SET price = ? WHERE id = ?', (new_price, user_state[message.from_user.id]['product_id']))
        conn.commit()
        conn.close()
        bot.reply_to(message, f"✅ تم تحديث السعر إلى {int(new_price)}$", reply_markup=main_keyboard())
        del user_state[message.from_user.id]
    except:
        bot.reply_to(message, "❌ السعر يجب أن يكون *رقم*. جرب مرة أخرى:", parse_mode='Markdown')

@bot.message_handler(func=lambda message: message.from_user.id in user_state and user_state[message.from_user.id].get('step') == 'edit_description')
def edit_description(message):
    if not is_authorized(message.from_user.id): return
    conn = get_db()
    conn.execute('UPDATE products SET description = ? WHERE id = ?', (message.text, user_state[message.from_user.id]['product_id']))
    conn.commit()
    conn.close()
    bot.reply_to(message, "✅ تم تحديث الوصف بنجاح", reply_markup=main_keyboard())
    del user_state[message.from_user.id]

# ================== حذف منتج ==================
@bot.message_handler(func=lambda message: message.text == "🗑️ حذف منتج")
def delete_product_button(message):
    if not is_authorized(message.from_user.id): return
    user_state[message.from_user.id] = {'step': 'delete_id'}
    bot.reply_to(message, "📝 أرسل *ID* المنتج (أول 8 حروف أو كامل):", parse_mode='Markdown')

@bot.message_handler(func=lambda message: message.from_user.id in user_state and user_state[message.from_user.id].get('step') == 'delete_id')
def delete_id(message):
    if not is_authorized(message.from_user.id): return
    product = find_product_by_partial_id(message.text.strip())
    if not product:
        bot.reply_to(message, "❌ منتج غير موجود. تأكد من ID (استخدم /list).")
        del user_state[message.from_user.id]
        return
    conn = get_db()
    conn.execute('DELETE FROM products WHERE id = ?', (product['id'],))
    conn.commit()
    conn.close()
    bot.reply_to(message, f"🗑️ تم حذف المنتج *{product['name']}* بنجاح!", reply_markup=main_keyboard(), parse_mode='Markdown')
    del user_state[message.from_user.id]

# ================== الطلبات والمستخدمين ==================
@bot.message_handler(func=lambda message: message.text == "📋 الطلبات")
def orders_button(message):
    if not is_authorized(message.from_user.id): return
    conn = get_db()
    orders = conn.execute('SELECT * FROM orders').fetchall()
    conn.close()
    if not orders:
        bot.reply_to(message, "📭 لا توجد طلبات.")
        return
    msg = "📋 *الطلبات:*\n"
    for o in orders:
        msg += f"\n👤 {o['customer_name']} | @{o['customer_username']} | {o['payment_status']}"
    bot.reply_to(message, msg, parse_mode='Markdown')

@bot.message_handler(func=lambda message: message.text == "👥 المستخدمين")
def users_button(message):
    if message.from_user.id != OWNER_ID:
        bot.reply_to(message, "⛔ فقط المالك.")
        return
    conn = get_db()
    users = conn.execute('SELECT * FROM authorized_users').fetchall()
    conn.close()
    if not users:
        bot.reply_to(message, "📭 لا يوجد مستخدمون.")
        return
    msg = "👥 *المستخدمون المخولون:*\n"
    for u in users:
        msg += f"\n🆔 {u['user_id']} | بواسطة: {u['granted_by']}"
    bot.reply_to(message, msg, parse_mode='Markdown')

@bot.message_handler(func=lambda message: message.text == "🔑 منح صلاحية")
def grant_button(message):
    if message.from_user.id != OWNER_ID:
        bot.reply_to(message, "⛔ فقط المالك يمكنه منح الصلاحيات.")
        return
    user_state[message.from_user.id] = {'step': 'grant_id'}
    bot.reply_to(message, "📝 أرسل *ايدي* المستخدم (رقم فقط):", parse_mode='Markdown')

@bot.message_handler(func=lambda message: message.from_user.id in user_state and user_state[message.from_user.id].get('step') == 'grant_id')
def grant_id(message):
    if message.from_user.id != OWNER_ID:
        bot.reply_to(message, "⛔ غير مصرح.")
        return
    try:
        user_id = message.text.strip()
        conn = get_db()
        existing = conn.execute('SELECT * FROM authorized_users WHERE user_id = ?', (user_id,)).fetchone()
        if existing:
            bot.reply_to(message, f"ℹ️ المستخدم {user_id} لديه صلاحية بالفعل.")
            del user_state[message.from_user.id]
            conn.close()
            return
        conn.execute('INSERT INTO authorized_users (user_id, granted_by, granted_at) VALUES (?, ?, ?)',
                     (user_id, str(message.from_user.id), datetime.utcnow().isoformat()))
        conn.commit()
        conn.close()
        bot.reply_to(message, f"✅ تم منح الصلاحية للمستخدم {user_id} بنجاح!", reply_markup=main_keyboard())
        del user_state[message.from_user.id]
    except:
        bot.reply_to(message, "❌ حدث خطأ، تأكد من أن الايدي رقم صحيح.")

# ================== زر الإلغاء (شامل) ==================
@bot.message_handler(func=lambda message: message.text == "❌ إلغاء العملية")
def cancel(message):
    cancel_operation(message)

def run_bot():
    print("🤖 البوت يعمل...")
    bot.polling(none_stop=True)

if __name__ == '__main__':
    bot_thread = threading.Thread(target=run_bot)
    bot_thread.start()
    print("🔥 السيرفر يعمل على http://localhost:5000")
    app.run(host='0.0.0.0', port=5000, debug=False)