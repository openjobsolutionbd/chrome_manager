# chrome_manager

এখানে তিনটি আলাদা টুল আছে, তিনটি আলাদা ফোল্ডারে। একটা অন্যটার ওপর নির্ভর করে না।

> নিয়ম: প্রতিটি পরিবর্তনের সাথে এই ফাইল, ওই ফোল্ডারের `README.md` আর `NOTES.md` আপডেট করতে হয় (নিয়ম `NOTES.md`-এর একদম উপরে)।

## ভার্সন (কোন সেকশনে এখন কোন ভার্সন)
| সেকশন | ফোল্ডার | ভার্সন | পরিবর্তনের ইতিহাস |
|---|---|---|---|
| ১ | `1-claude-limit-closer-with-extention/` | এক্সটেনশন 1.5 · launcher.py 1.2.1 | [`CHANGELOG.md`](1-claude-limit-closer-with-extention/CHANGELOG.md) |
| ২ | `2-chrome-opener-with-py/` | Chrome Opener 2.1.0 | [`CHANGELOG.md`](2-chrome-opener-with-py/CHANGELOG.md) |
| ৩ | `3-only-chrome-opener/` | Only Chrome Opener 1.0.0 | [`CHANGELOG.md`](3-only-chrome-opener/CHANGELOG.md) |

প্রতিটি ভার্সনের জন্য GitHub-এ একটা ট্যাগ থাকে: `claude-limit-closer-v1.5`, `chrome-opener-v2.1.0`, `only-chrome-opener-v1.0.0`।

## ফোল্ডার সাজানো
```
chrome_manager/
├── README.md                              ← এই পাতা (সূচি + ভার্সন)
├── NOTES.md                               ← Claude-এর জন্য নিয়ম ও সিদ্ধান্ত
├── .gitignore                             ← ব্যক্তিগত ফাইল ভুলে কমিট হওয়া আটকায়
├── 1-claude-limit-closer-with-extention/  ← সেকশন ১
│   ├── README.md
│   ├── CHANGELOG.md
│   ├── NOTES.md
│   ├── extension/                         (Chrome এক্সটেনশন)
│   ├── launcher.py
│   └── launcher.bat
├── 2-chrome-opener-with-py/               ← সেকশন ২
│   ├── README.md
│   ├── CHANGELOG.md
│   ├── NOTES.md
│   ├── Chrome_Opener.py
│   └── Chrome_Opener_Shut_Down.py
└── 3-only-chrome-opener/                  ← সেকশন ৩
    ├── README.md
    ├── CHANGELOG.md
    ├── NOTES.md
    ├── Chrome_Opener.py
    ├── Chrome_Opener.bat
    ├── Chrome_Opener_Close_All.py
    └── Chrome_Opener_Close_All.bat
```

## ১. Claude Limit Closer — ফোল্ডার `1-claude-limit-closer-with-extention/`
Chrome এক্সটেনশন + `launcher.py`। প্রোফাইল ১০টি করে খোলে, থেমে থাকা চ্যাটে "Continue" চাপে, ফ্রি লিমিট শেষ হলে ওই প্রোফাইল বন্ধ করে।
বিস্তারিত: [`1-claude-limit-closer-with-extention/README.md`](1-claude-limit-closer-with-extention/README.md)

## ২. Chrome Opener — ফোল্ডার `2-chrome-opener-with-py/`
Python টুল (`Chrome_Opener.py`)। প্রোফাইল একটা একটা করে খোলে, মেইন ট্যাবেই `claude.ai/chats`-এ গিয়ে চ্যাট দেখে, থেমে থাকা চ্যাটে "Continue" / "Try again" চাপে, লিমিট শেষ হলে রিসেটের সময়ে নিজে আবার ফিরে আসে। সাথে `Chrome_Opener_Shut_Down.py` (সব অ্যাপ বন্ধ করে পিসি শাট ডাউন)।
বিস্তারিত: [`2-chrome-opener-with-py/README.md`](2-chrome-opener-with-py/README.md)

## ৩. Only Chrome Opener — ফোল্ডার `3-only-chrome-opener/`
Python টুল (`Chrome_Opener.py`)। **শুধু** প্রোফাইল খোলে আর লিমিট ধরে; চ্যাটে ঢুকে কিছু চাপে না। শুরুতে একসাথে ১০টা প্রোফাইল ব্যাচে খোলে, খোলা জানালাগুলো বারবার স্ক্যান করে, ফ্রি লিমিটের মেসেজ দেখলে ওই প্রোফাইল বন্ধ করে, আর রিসেটের সময় হলে নিজে আবার খোলে। সাথে `Chrome_Opener_Close_All` (সব Chrome জানালা বন্ধ)।
বিস্তারিত: [`3-only-chrome-opener/README.md`](3-only-chrome-opener/README.md)

## Claude-এর জন্য নোট
[`NOTES.md`](NOTES.md) — সবার জন্য নিয়ম। প্রতিটা সেকশনের নিজের `NOTES.md` আছে (সিদ্ধান্ত, সমস্যা, কীভাবে কাজ করে)।
