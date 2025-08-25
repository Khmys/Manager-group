# Meneja wa Vikundi vya Telegram kwa Webhook 🚀

Bot hii ya Telegram imeundwa kusimamia vikundi kwa kutumia teknolojia ya Webhook. Inatumia python-telegram-bot pamoja na Starlette na Uvicorn kwa utendaji wa haraka na wa kisasa.

## ⚙️ Vipengele Muhimu

- ✅ Karibu ya kipekee kwa wanachama wapya
- ✅ Ujumbe wa kuondoka unafutwa moja kwa moja
- ✅ Mmiliki wa bot hupokea ujumbe wa heshima anapoondoka
- ✅ Ujumbe wa kukaribisha unafutwa baada ya sekunde 60
- ✅ Hitilafu hutumwa kwenye kundi maalum la kuripoti makosa
- ✅ Bot huwasiliana na Telegram kupitia Webhook (hakuna polling)

## 🧠 Teknolojia Zinazotumika

| Kipengele              | Maelezo                          |
|------------------------|----------------------------------|
| Lugha ya programu      | Python 3.11                      |
| Telegram API           | python-telegram-bot v20+       |
| Web framework          | Starlette                      |
| Web server             | Uvicorn                        |
| Deployment             | Docker / Render / Railway / Heroku |

## 📦 Jinsi ya Kuendesha Bot

#### 1. Weka environment variables kwenye .env au kwenye dashboard ya hosting:

`env
Token=YOURBOTTOKEN
OWNERID=YOURTELEGRAMUSERID
ERRORGROUPID=GROUPIDFORERRORREPORTS
URL=https://your-app-url.com
PORT=10000
`

#### 2. Sakinisha dependencies:

`bash
pip install -r requirements.txt
`

#### 3. Endesha bot kwa Webhook:

`bash
python bot.py
`

Bot itajiunga na Telegram kupitia URL/telegram na kuanza kupokea updates.

## 🐳 Dockerfile (mfano)

`Dockerfile
FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 10000

CMD ["python", "bot.py"]
`

# 🔐 Usalama

- Token na taarifa nyeti zinahifadhiwa kwenye environment variables
- Hakuna credentials zinazowekwa hadharani
- .env inapaswa kuorodheshwa kwenye .gitignore
- Hitilafu hutumwa kwa admin kupitia ERRORGROUPID

## 📌 Jinsi ya Kuongeza Bot kwenye Kundi

Ongeza bot kwenye kundi lako na mpe ruhusa ya kusoma na kuandika ujumbe. Bot ataanza:

- Kukaribisha wanachama wapya kwa furaha 🎉  
- Kufuta ujumbe wa kuondoka kwa usafi wa mazungumzo 🧹  
- Kuripoti hitilafu kwa admin kwa uwazi 📩  

#### 👉 Bonyeza hapa kumwongeza Meneja

##📄 Leseni

Mradi huu unafuata leseni ya MIT. Imetafsiriwa pia kwa Kiswahili ili iweze kueleweka na jamii pana.

