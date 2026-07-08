from flask import Flask, render_template, request, redirect, url_for, jsonify, session, flash
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
from werkzeug.utils import secure_filename
import json, os, secrets, string

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'aoneart_secret_key_2024')

# --- Database config (Turso in production, local SQLite fallback for dev) ---
TURSO_DATABASE_URL = os.environ.get('TURSO_DATABASE_URL')
TURSO_AUTH_TOKEN = os.environ.get('TURSO_AUTH_TOKEN')

if TURSO_DATABASE_URL and TURSO_AUTH_TOKEN:
    # Turso's URL comes as libsql://..., SQLAlchemy needs the sqlite+libsql:// scheme
    _db_host = TURSO_DATABASE_URL.replace('libsql://', '')
    app.config['SQLALCHEMY_DATABASE_URI'] = f"sqlite+libsql://{_db_host}?secure=true"
    app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
        'connect_args': {'auth_token': TURSO_AUTH_TOKEN}
    }
else:
    # Falls back to local file when running on your own machine without Turso env vars set
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///oneart.db'

app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['UPLOAD_FOLDER'] = os.path.join(os.path.dirname(__file__), 'static', 'uploads')
app.config['MAX_CONTENT_LENGTH'] = 8 * 1024 * 1024
ALLOWED_EXT = {'png', 'jpg', 'jpeg', 'webp', 'gif'}
ADMIN_PASSWORD = os.environ.get('ADMIN_PASSWORD', 'aoneart2024')

# --- Cloudinary config (for product image uploads - Vercel's filesystem is read-only) ---
import cloudinary
import cloudinary.uploader

CLOUDINARY_ENABLED = bool(os.environ.get('CLOUDINARY_CLOUD_NAME'))
if CLOUDINARY_ENABLED:
    cloudinary.config(
        cloud_name = os.environ.get('CLOUDINARY_CLOUD_NAME'),
        api_key    = os.environ.get('CLOUDINARY_API_KEY'),
        api_secret = os.environ.get('CLOUDINARY_API_SECRET'),
        secure     = True
    )

db = SQLAlchemy(app)

# Custom Jinja2 filters
@app.template_filter('from_json')
def from_json(value):
    try:
        return json.loads(value or '[]')
    except Exception:
        return []

@app.template_filter('product_img')
def product_img(image):
    """Old products store a local path like 'products/product1.jpeg' (served from
    /static/images/...). New uploads (via Cloudinary) store a full https:// URL.
    This filter renders the correct <img src> for either case."""
    if not image:
        return url_for('static', filename='images/favicon.png')
    if image.startswith('http://') or image.startswith('https://'):
        return image
    return url_for('static', filename='images/' + image)

# ═══════════════════════════════════════════════════
# MODELS
# ═══════════════════════════════════════════════════

class Product(db.Model):
    id          = db.Column(db.Integer, primary_key=True)
    name        = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text)
    price       = db.Column(db.Float, nullable=False)
    category    = db.Column(db.String(100))
    image       = db.Column(db.String(300))
    stock       = db.Column(db.Integer, default=10)
    featured    = db.Column(db.Boolean, default=False)
    created_at  = db.Column(db.DateTime, default=datetime.utcnow)
    reviews     = db.relationship('Review', backref='product', lazy=True, cascade='all,delete')

def generate_order_ref():
    """Generate a random 10-character alphanumeric order reference (e.g. OA-K4RX92BN)."""
    alphabet = string.ascii_uppercase + string.digits
    return 'OA-' + ''.join(secrets.choice(alphabet) for _ in range(8))

class Order(db.Model):
    id               = db.Column(db.Integer, primary_key=True)
    order_ref        = db.Column(db.String(20), unique=True, nullable=False, default=generate_order_ref)
    customer_name    = db.Column(db.String(200), nullable=False)
    customer_email   = db.Column(db.String(200))
    customer_phone   = db.Column(db.String(50), nullable=False)
    customer_address = db.Column(db.Text, nullable=False)
    city             = db.Column(db.String(100))
    items            = db.Column(db.Text)
    total            = db.Column(db.Float)
    payment_method   = db.Column(db.String(50))
    payment_number   = db.Column(db.String(50))
    status           = db.Column(db.String(50), default='Pending')
    created_at       = db.Column(db.DateTime, default=datetime.utcnow)
    notes            = db.Column(db.Text)

class Review(db.Model):
    id         = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey('product.id'), nullable=False)
    name       = db.Column(db.String(100), nullable=False)
    city       = db.Column(db.String(80))
    rating     = db.Column(db.Integer, default=5)
    body       = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

# ═══════════════════════════════════════════════════
# HELPERS
# ═══════════════════════════════════════════════════

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXT

def admin_required():
    return session.get('admin_logged_in') is True

def cart_total_count():
    cart = session.get('cart', [])
    return sum(i['qty'] for i in cart)

def build_whatsapp_order_msg(order):
    items_data = json.loads(order.items or '[]')
    lines = [f"*New Order {order.order_ref}* 🛒"]
    lines.append(f"👤 {order.customer_name}")
    lines.append(f"📞 {order.customer_phone}")
    lines.append(f"📍 {order.city} — {order.customer_address}")
    lines.append("")
    for it in items_data:
        lines.append(f"• {it['name']} × {it['qty']} = Rs. {it['price']*it['qty']:,.0f}")
    lines.append("")
    lines.append(f"💰 *Total: Rs. {order.total:,.0f}*")
    lines.append(f"💳 Payment: {order.payment_method.upper()}")
    if order.payment_number:
        lines.append(f"🧾 Txn Ref: {order.payment_number}")
    return "%0A".join(l.replace(" ", "%20").replace("*", "*") for l in lines)

# ═══════════════════════════════════════════════════
# SEED DATA
# ═══════════════════════════════════════════════════

def seed_data():
    if Product.query.count() == 0:
        products = [
            Product(name="Diamond Geometric Wall Clock",
                    description="A stunning geometric wire-frame wall clock with golden hands. Features an intricate diamond polygon design crafted from premium black metal. Perfect for modern and contemporary interiors. Size: 50cm diameter. Battery operated (AA).",
                    price=3500, category="Wall Clocks", image="products/product1.jpeg", stock=15, featured=True),
            Product(name="Steampunk Gear Wall Clock",
                    description="Industrial steampunk clock with exposed gear mechanisms and Roman numerals. Unique open-face horseshoe design with moving mechanical gears. A statement piece for any room. Size: 60cm. Silent motor.",
                    price=4800, category="Wall Clocks", image="products/product2.jpeg", stock=8, featured=True),
            Product(name="Minimalist Arrow Wall Clock",
                    description="Ultra-sleek minimalist wall clock with arrow-style hands and clean line design. Black matte finish that blends seamlessly with any interior style. Size: 40cm. Battery operated.",
                    price=2800, category="Wall Clocks", image="products/product3.jpeg", stock=20, featured=False),
            Product(name="City Skyline Key Holder",
                    description="Decorative laser-cut metal key holder featuring a beautiful city skyline with HOME lettering. Includes 5 hooks. Matte black powder coat. A functional yet artistic piece for your entryway. Size: 45cm × 18cm.",
                    price=1800, category="Home Decor", image="products/product4.jpeg", stock=25, featured=True),
            Product(name="Islamic Crescent Moon Clock",
                    description="Majestic Islamic crescent moon wall clock with Arabic Bismillah calligraphy. Black and gold finish with intricate arabesque patterns. Includes star accents. A spiritual centrepiece. Size: 65cm × 60cm.",
                    price=5500, category="Islamic Art", image="products/product5.jpeg", stock=12, featured=True),
            Product(name="Abstract Metal Wall Art",
                    description="Premium abstract metal wall art piece with flowing modern design. Handcrafted with precision laser cutting. Adds a sophisticated artistic touch to living rooms and offices. Size: 50cm × 50cm.",
                    price=3200, category="Wall Art", image="products/product6.jpeg", stock=10, featured=False),
            Product(name="Floral Laser-Cut Wall Decor",
                    description="Elegant floral pattern laser-cut metal wall decoration. Delicate petals and leaves crafted with precision. Beautiful shadow patterns when lit. Perfect for bedrooms and dining rooms. Size: 45cm × 45cm.",
                    price=2500, category="Wall Art", image="products/product7.jpeg", stock=18, featured=True),
        ]
        for p in products:
            db.session.add(p)
        db.session.commit()

    if Review.query.count() == 0:
        reviews = [
            Review(product_id=5, name="Ahmed Hassan", city="Lahore", rating=5,
                   body="The Islamic crescent clock is absolutely breathtaking. The craftsmanship is unmatched and the gold detailing is stunning. Everyone who visits asks where I got it!"),
            Review(product_id=1, name="Fatima Zahra", city="Karachi", rating=5,
                   body="Ordered the geometric clock and it arrived perfectly packaged. The quality exceeded my expectations — it's a real statement piece in my living room."),
            Review(product_id=4, name="Usman Malik", city="Islamabad", rating=5,
                   body="The city skyline key holder is a perfect blend of art and function. Easy COD payment and fast delivery. Will definitely order again!"),
            Review(product_id=2, name="Sara Khan", city="Faisalabad", rating=5,
                   body="The steampunk gear clock is incredible. My guests can't stop admiring it. Packaging was excellent and delivery was fast. Highly recommend AOneArt!"),
        ]
        for r in reviews:
            db.session.add(r)
        db.session.commit()

# ═══════════════════════════════════════════════════
# PUBLIC ROUTES
# ═══════════════════════════════════════════════════

@app.route('/')
def index():
    featured   = Product.query.filter_by(featured=True).all()
    categories = [c[0] for c in db.session.query(Product.category).distinct().all()]
    reviews    = Review.query.order_by(Review.created_at.desc()).limit(3).all()
    total_orders = Order.query.count()
    return render_template('index.html', featured=featured, categories=categories,
                           reviews=reviews, total_orders=total_orders)

@app.route('/shop')
def shop():
    category  = request.args.get('category', '')
    search    = request.args.get('search', '')
    sort      = request.args.get('sort', 'default')
    min_price = request.args.get('min_price', type=float)
    max_price = request.args.get('max_price', type=float)

    query = Product.query
    if category:
        query = query.filter_by(category=category)
    if search:
        query = query.filter(
            Product.name.ilike(f'%{search}%') | Product.description.ilike(f'%{search}%')
        )
    if min_price is not None:
        query = query.filter(Product.price >= min_price)
    if max_price is not None:
        query = query.filter(Product.price <= max_price)
    if sort == 'price_asc':
        query = query.order_by(Product.price.asc())
    elif sort == 'price_desc':
        query = query.order_by(Product.price.desc())
    elif sort == 'newest':
        query = query.order_by(Product.created_at.desc())
    elif sort == 'featured':
        query = query.order_by(Product.featured.desc())

    products   = query.all()
    categories = [c[0] for c in db.session.query(Product.category).distinct().all()]
    all_prices = [p.price for p in Product.query.all()]
    return render_template('shop.html', products=products, categories=categories,
                           current_category=category, search=search, sort=sort,
                           min_price=min_price, max_price=max_price,
                           price_min=int(min(all_prices)) if all_prices else 0,
                           price_max=int(max(all_prices)) if all_prices else 10000)

@app.route('/product/<int:pid>')
def product_detail(pid):
    product = Product.query.get_or_404(pid)
    related = Product.query.filter_by(category=product.category).filter(Product.id != pid).limit(4).all()
    reviews = Review.query.filter_by(product_id=pid).order_by(Review.created_at.desc()).all()
    avg_rating = round(sum(r.rating for r in reviews) / len(reviews), 1) if reviews else 0
    return render_template('product.html', product=product, related=related,
                           reviews=reviews, avg_rating=avg_rating)

@app.route('/product/<int:pid>/review', methods=['POST'])
def add_review(pid):
    Product.query.get_or_404(pid)
    rev = Review(
        product_id=pid,
        name=request.form.get('name', 'Anonymous'),
        city=request.form.get('city', ''),
        rating=int(request.form.get('rating', 5)),
        body=request.form.get('body', '')
    )
    db.session.add(rev)
    db.session.commit()
    flash('Thank you for your review!', 'success')
    return redirect(url_for('product_detail', pid=pid) + '#reviews')

@app.route('/cart')
def cart():
    cart_items = session.get('cart', [])
    products, total = [], 0
    for item in cart_items:
        p = Product.query.get(item['id'])
        if p:
            sub = p.price * item['qty']
            total += sub
            products.append({'product': p, 'qty': item['qty'], 'subtotal': sub})
    return render_template('cart.html', cart=products, total=total)

@app.route('/add_to_cart/<int:pid>', methods=['POST'])
def add_to_cart(pid):
    qty  = int(request.form.get('qty', 1))
    cart = session.get('cart', [])
    for item in cart:
        if item['id'] == pid:
            item['qty'] += qty
            session['cart'] = cart
            flash('Cart updated!', 'success')
            return redirect(request.referrer or url_for('cart'))
    cart.append({'id': pid, 'qty': qty})
    session['cart'] = cart
    flash('Added to cart!', 'success')
    return redirect(request.referrer or url_for('cart'))

@app.route('/remove_from_cart/<int:pid>')
def remove_from_cart(pid):
    session['cart'] = [i for i in session.get('cart', []) if i['id'] != pid]
    flash('Item removed.', 'info')
    return redirect(url_for('cart'))

@app.route('/update_cart/<int:pid>', methods=['POST'])
def update_cart(pid):
    qty  = int(request.form.get('qty', 1))
    cart = session.get('cart', [])
    for item in cart:
        if item['id'] == pid:
            item['qty'] = max(1, qty)
    session['cart'] = cart
    return redirect(url_for('cart'))

@app.route('/cart_count')
def cart_count():
    count = sum(i['qty'] for i in session.get('cart', []))
    return jsonify({'count': count})

@app.route('/checkout', methods=['GET', 'POST'])
def checkout():
    cart_items = session.get('cart', [])
    if not cart_items:
        flash('Your cart is empty!', 'warning')
        return redirect(url_for('shop'))

    products, total = [], 0
    for item in cart_items:
        p = Product.query.get(item['id'])
        if p:
            sub = p.price * item['qty']
            total += sub
            products.append({'product': p, 'qty': item['qty'], 'subtotal': sub})

    if request.method == 'POST':
        items_json = json.dumps([{
            'id': i['product'].id, 'name': i['product'].name,
            'qty': i['qty'], 'price': i['product'].price
        } for i in products])
        order = Order(
            customer_name    = request.form.get('name'),
            customer_email   = request.form.get('email'),
            customer_phone   = request.form.get('phone'),
            customer_address = request.form.get('address'),
            city             = request.form.get('city'),
            items            = items_json,
            total            = total,
            payment_method   = request.form.get('payment_method'),
            payment_number   = request.form.get('payment_number', ''),
            notes            = request.form.get('notes', '')
        )
        db.session.add(order)
        db.session.commit()
        session['cart'] = []
        return redirect(url_for('order_success', oid=order.id))

    return render_template('checkout.html', cart=products, total=total)

@app.route('/order/success/<int:oid>')
def order_success(oid):
    order   = Order.query.get_or_404(oid)
    wa_msg  = build_whatsapp_order_msg(order)
    wa_link = f"https://wa.me/923076363893?text={wa_msg}"
    return render_template('order_success.html', order=order, wa_link=wa_link)

@app.route('/track')
def track_order():
    order = None
    oid   = request.args.get('order_id', '').strip().upper()
    if oid:
        try:
            # Look up by random order_ref (e.g. OA-K4RX92BN)
            order = Order.query.filter_by(order_ref=oid).first()
        except:
            pass
    return render_template('track.html', order=order, searched=bool(oid))

@app.route('/contact')
def contact():
    return render_template('contact.html')

@app.route('/about')
def about():
    return render_template('about.html')

@app.route('/faq')
def faq():
    return render_template('faq.html')

# ═══════════════════════════════════════════════════
# ADMIN ROUTES
# ═══════════════════════════════════════════════════

@app.route('/admin', methods=['GET','POST'])
def admin_login():
    if admin_required():
        return redirect(url_for('admin_dashboard'))
    if request.method == 'POST':
        if request.form.get('password') == ADMIN_PASSWORD:
            session['admin_logged_in'] = True
            return redirect(url_for('admin_dashboard'))
        flash('Wrong password!', 'danger')
    return render_template('admin/login.html')

@app.route('/admin/logout')
def admin_logout():
    session.pop('admin_logged_in', None)
    return redirect(url_for('admin_login'))

@app.route('/admin/dashboard')
def admin_dashboard():
    if not admin_required():
        return redirect(url_for('admin_login'))
    orders   = Order.query.order_by(Order.created_at.desc()).all()
    products = Product.query.order_by(Product.created_at.desc()).all()
    revenue  = sum(o.total or 0 for o in orders if o.status != 'Cancelled')
    pending  = Order.query.filter_by(status='Pending').count()
    shipped  = Order.query.filter_by(status='Shipped').count()
    # Revenue by day (last 7)
    from collections import defaultdict
    daily = defaultdict(float)
    for o in orders:
        if o.status != 'Cancelled':
            day = o.created_at.strftime('%d %b')
            daily[day] += o.total or 0
    return render_template('admin/dashboard.html',
                           orders=orders, products=products,
                           revenue=revenue, pending=pending, shipped=shipped,
                           daily=dict(daily))

@app.route('/admin/orders')
def admin_orders():
    if not admin_required():
        return redirect(url_for('admin_login'))
    status = request.args.get('status', '')
    q = Order.query.order_by(Order.created_at.desc())
    if status:
        q = q.filter_by(status=status)
    orders = q.all()
    return render_template('admin/orders.html', orders=orders, status_filter=status)

@app.route('/admin/order/<int:oid>')
def admin_order_detail(oid):
    if not admin_required():
        return redirect(url_for('admin_login'))
    order = Order.query.get_or_404(oid)
    items = json.loads(order.items or '[]')
    wa_msg  = build_whatsapp_order_msg(order)
    wa_link = f"https://wa.me/9{order.customer_phone.replace('+','').replace('-','').replace(' ','')}?text={wa_msg}"
    return render_template('admin/order_detail.html', order=order, items=items, wa_link=wa_link)

@app.route('/admin/order/<int:oid>/status', methods=['POST'])
def admin_update_status(oid):
    if not admin_required():
        return redirect(url_for('admin_login'))
    order = Order.query.get_or_404(oid)
    order.status = request.form.get('status', order.status)
    db.session.commit()
    flash(f'Order {order.order_ref} status updated to {order.status}', 'success')
    return redirect(url_for('admin_order_detail', oid=oid))

@app.route('/admin/products')
def admin_products():
    if not admin_required():
        return redirect(url_for('admin_login'))
    products = Product.query.order_by(Product.created_at.desc()).all()
    return render_template('admin/products.html', products=products)

@app.route('/admin/product/new', methods=['GET','POST'])
def admin_product_new():
    if not admin_required():
        return redirect(url_for('admin_login'))
    if request.method == 'POST':
        img_path = ''
        file = request.files.get('image')
        if file and allowed_file(file.filename):
            if CLOUDINARY_ENABLED:
                result = cloudinary.uploader.upload(file, folder='oneart_products')
                img_path = result['secure_url']
            else:
                fn = secure_filename(file.filename)
                fn = f"{datetime.utcnow().strftime('%Y%m%d%H%M%S')}_{fn}"
                file.save(os.path.join(app.config['UPLOAD_FOLDER'], fn))
                img_path = f"uploads/{fn}"
        p = Product(
            name        = request.form.get('name'),
            description = request.form.get('description'),
            price       = float(request.form.get('price', 0)),
            category    = request.form.get('category'),
            stock       = int(request.form.get('stock', 0)),
            featured    = 'featured' in request.form,
            image       = img_path
        )
        db.session.add(p)
        db.session.commit()
        flash('Product added!', 'success')
        return redirect(url_for('admin_products'))
    categories = [c[0] for c in db.session.query(Product.category).distinct().all()]
    return render_template('admin/product_form.html', product=None, categories=categories)

@app.route('/admin/product/<int:pid>/edit', methods=['GET','POST'])
def admin_product_edit(pid):
    if not admin_required():
        return redirect(url_for('admin_login'))
    p = Product.query.get_or_404(pid)
    if request.method == 'POST':
        p.name        = request.form.get('name')
        p.description = request.form.get('description')
        p.price       = float(request.form.get('price', p.price))
        p.category    = request.form.get('category')
        p.stock       = int(request.form.get('stock', p.stock))
        p.featured    = 'featured' in request.form
        file = request.files.get('image')
        if file and file.filename and allowed_file(file.filename):
            if CLOUDINARY_ENABLED:
                result = cloudinary.uploader.upload(file, folder='oneart_products')
                p.image = result['secure_url']
            else:
                fn = secure_filename(file.filename)
                fn = f"{datetime.utcnow().strftime('%Y%m%d%H%M%S')}_{fn}"
                file.save(os.path.join(app.config['UPLOAD_FOLDER'], fn))
                p.image = f"uploads/{fn}"
        db.session.commit()
        flash('Product updated!', 'success')
        return redirect(url_for('admin_products'))
    categories = [c[0] for c in db.session.query(Product.category).distinct().all()]
    return render_template('admin/product_form.html', product=p, categories=categories)

@app.route('/admin/product/<int:pid>/delete', methods=['POST'])
def admin_product_delete(pid):
    if not admin_required():
        return redirect(url_for('admin_login'))
    p = Product.query.get_or_404(pid)
    db.session.delete(p)
    db.session.commit()
    flash('Product deleted.', 'info')
    return redirect(url_for('admin_products'))

@app.route('/admin/reviews')
def admin_reviews():
    if not admin_required():
        return redirect(url_for('admin_login'))
    reviews = Review.query.order_by(Review.created_at.desc()).all()
    return render_template('admin/reviews.html', reviews=reviews)

@app.route('/admin/review/<int:rid>/delete', methods=['POST'])
def admin_review_delete(rid):
    if not admin_required():
        return redirect(url_for('admin_login'))
    r = Review.query.get_or_404(rid)
    db.session.delete(r)
    db.session.commit()
    flash('Review deleted.', 'info')
    return redirect(url_for('admin_reviews'))

# ═══════════════════════════════════════════════════
# API
# ═══════════════════════════════════════════════════

@app.route('/api/order/<int:oid>/status')
def api_order_status(oid):
    o = Order.query.get_or_404(oid)
    return jsonify({'id': oid, 'status': o.status, 'total': o.total,
                    'customer': o.customer_name, 'city': o.city})

# Runs on import too (needed for Vercel, since it never hits __main__),
# and also when you run this file directly for local development.
try:
    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
except OSError:
    pass  # read-only filesystem in production (e.g. Vercel) - expected, ignore

with app.app_context():
    db.create_all()
    seed_data()

if __name__ == '__main__':
    app.run(debug=True, port=5000)
