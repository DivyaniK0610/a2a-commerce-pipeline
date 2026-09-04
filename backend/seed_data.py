"""
seed_data.py — Seeds the SQLite inventory with sample tech products
Run once: python seed_data.py
A2A Commerce Pipeline | Razorpay Buildathon Track 1
"""

import uuid
from database import init_db, get_connection

PRODUCTS = [
    {
        "item_id": str(uuid.uuid4()),
        "name": "Mechanical Keyboard",
        "description": "TKL RGB mechanical keyboard with Cherry MX Blue switches, USB-C, 87 keys",
        "price": 3499.00,
        "stock_count": 15,
        "category": "Peripherals"
    },
    {
        "item_id": str(uuid.uuid4()),
        "name": "Wireless Mouse",
        "description": "Ergonomic wireless mouse, 2.4GHz, 3200 DPI, 12-month battery life",
        "price": 1299.00,
        "stock_count": 28,
        "category": "Peripherals"
    },
    {
        "item_id": str(uuid.uuid4()),
        "name": "USB-C Hub",
        "description": "7-in-1 USB-C hub: HDMI 4K, 3x USB-A, SD card, PD 100W, Ethernet",
        "price": 2199.00,
        "stock_count": 20,
        "category": "Accessories"
    },
    {
        "item_id": str(uuid.uuid4()),
        "name": "Monitor Stand",
        "description": "Adjustable aluminum monitor stand with height/tilt control and cable management",
        "price": 1899.00,
        "stock_count": 3,   # Low stock — perfect for graceful-failure demo
        "category": "Accessories"
    },
    {
        "item_id": str(uuid.uuid4()),
        "name": "HD Webcam",
        "description": "1080p 60fps webcam with built-in noise-cancelling mic, auto-focus, plug & play",
        "price": 2799.00,
        "stock_count": 11,
        "category": "Peripherals"
    },
    {
        "item_id": str(uuid.uuid4()),
        "name": "Noise Cancelling Headset",
        "description": "Over-ear headset with ANC, 40mm drivers, USB + 3.5mm, 30hr battery",
        "price": 4999.00,
        "stock_count": 8,
        "category": "Audio"
    },
]


def seed():
    init_db()
    conn = get_connection()
    cur = conn.cursor()

    # Clear existing inventory before seeding
    cur.execute("DELETE FROM inventory")

    for product in PRODUCTS:
        cur.execute(
            """
            INSERT INTO inventory (item_id, name, description, price, stock_count, category)
            VALUES (:item_id, :name, :description, :price, :stock_count, :category)
            """,
            product
        )
        print(f"  [+] Seeded: {product['name']} (Rs.{product['price']}, stock: {product['stock_count']})")

    conn.commit()
    conn.close()
    print(f"\n[SEED] {len(PRODUCTS)} products seeded into inventory.\n")


if __name__ == "__main__":
    seed()
