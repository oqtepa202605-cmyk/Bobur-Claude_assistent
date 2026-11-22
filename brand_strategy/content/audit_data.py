# @architector_bobur — Instagram API ma'lumotlari (Windsor.ai orqali), 2026-yil 22-noyabrda olingan.
# Faqat API qaytargan real qiymatlar. Qo'lda o'zgartirmang; yangilash uchun qayta yuklab oling.

FETCHED = "22-noyabr 2026"
PERIOD = "23-oktabr — 21-noyabr 2026 (30 kun)"

PROFILE = {
    "username": "architector_bobur",
    "name": "Bobur Hayitov | Arxitektor",
    "biography": "🏛 𝗔𝗿𝘅𝗶𝘁𝗲𝗸𝘁𝗼𝗿 | 𝗗𝗶𝘇𝗮𝘆𝗻𝗲𝗿 • 𝟱 𝘆𝗶𝗹𝗹𝗶𝗸 𝘁𝗮𝗷𝗿𝗶𝗯𝗮\n📐 Interyer • Eksteryer • Arxitektura Chizmalari\n📩 𝖡𝖾𝗉𝗎𝗅 𝗄𝗈𝗇𝗌𝗎𝗅𝗍𝖺𝗍𝗌𝗂𝗒𝖺 𝗎𝖼𝗁𝗎𝗇 𝖣𝗂𝗋𝖾𝖼𝗍'𝗀𝖺 𝗒𝗈𝗓𝗂𝗇𝗀",
    "website": "https://t.me/HayitovBobur",
    "followers": 1774,
    "follows": 143,
    "media": 3,
}

# Kunlik akkaunt ko'rsatkichlari (oxirgi 30 kun): reach, views, yangi obunachilar
DAILY = {
    "reach": [0,0,0,0,0,0,0,0,1,0,0,0,0,2,0,1,0,0,0,0,0,2,1,1,0,0,0,0,1,1],
    "views": [0,0,0,0,0,0,0,0,0,0,0,0,0,6,0,0,0,0,0,0,0,5,1,1,0,0,0,0,18,19],
    "new_followers": [0,0,0,0,0,0,0,0,0,0,0,0,0,1,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0],
    "likes": 0, "comments": 0, "saves": 0, "shares": 0, "profile_links_taps": 0, "accounts_engaged": 0,
    "posts_in_period": 0,
}

# Obunachilar: jins.yosh -> soni (F = ayol, M = erkak, U = ko'rsatilmagan)
GENDER_AGE = {
    "F.13-17": 1, "F.18-24": 29, "F.25-34": 89, "F.35-44": 45, "F.45-54": 10, "F.65+": 1,
    "M.13-17": 2, "M.18-24": 75, "M.25-34": 329, "M.35-44": 117, "M.45-54": 14, "M.55-64": 5, "M.65+": 2,
    "U.13-17": 9, "U.18-24": 312, "U.25-34": 513, "U.35-44": 148, "U.45-54": 29, "U.55-64": 16, "U.65+": 15,
}

# Obunachilar: shahar -> soni (API qaytargan 45 shahar)
CITIES = {
    "Toshkent": 575, "Andijon": 73, "Samarqand": 69, "Loyish": 53, "Qo'qon": 46, "Nukus": 44,
    "Namangan": 42, "Buxoro": 37, "Navoiy": 36, "Mang'it": 35, "Salar": 32, "Urganch": 31,
    "To'rtko'l": 27, "Yangiyer": 26, "Moskva": 25, "O'rtaovul": 23, "Jizzax": 21, "Marg'ilon": 19,
    "Kosonsoy": 18, "Xiva": 17, "Farg'ona": 17, "Guliston (Sirdaryo)": 17, "Shahrisabz": 15, "Chirchiq": 15,
    "Zarafshon": 15, "Zomin": 14, "Romitan": 14, "Qibray": 13, "Qarshi": 12, "Yangiyo'l": 11,
    "Kogon": 11, "Do'stlik": 11, "Chordara (Navoiy)": 11, "Bishkek": 10, "Boysun": 9, "Asaka": 9,
    "Yaypan": 9, "Dushanbe": 8, "Gulistan": 8, "Oqtosh": 8, "Chust": 8, "Pop": 8,
    "Shahrixon": 7, "Gagarin": 7, "Hamza": 7,
}
TASHKENT_REGION = ["O'rtaovul", "Salar", "Chirchiq", "Qibray", "Yangiyo'l"]
ABROAD = ["Moskva", "Bishkek", "Dushanbe"]
