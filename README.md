# chrome_manager

এখানে দুটো আলাদা টুল আছে, দুটো আলাদা ফোল্ডারে। একটা অন্যটার ওপর নির্ভর করে না।

> নিয়ম: প্রতিটি পরিবর্তনের সাথে এই ফাইল, ওই ফোল্ডারের `README.md` আর `NOTES.md` আপডেট করতে হয় (নিয়ম `NOTES.md`-এর একদম উপরে)।

## ১. Claude Limit Closer — ফোল্ডার `claude-limit-closer/`
Chrome এক্সটেনশন + `launcher.py`। প্রোফাইল ১০টি করে খোলে, থেমে থাকা চ্যাটে "Continue" চাপে, ফ্রি লিমিট শেষ হলে ওই প্রোফাইল বন্ধ করে।
বিস্তারিত: [`claude-limit-closer/README.md`](claude-limit-closer/README.md)

## ২. Chrome Opener — ফোল্ডার `chrome-opener/`
Python টুল (`Chrome_Opener.py`)। প্রোফাইল একটা একটা করে খোলে, মেইন ট্যাবেই `claude.ai/chats`-এ গিয়ে চ্যাট দেখে, থেমে থাকা চ্যাটে "Continue" / "Try again" চাপে, লিমিট শেষ হলে রিসেটের সময়ে নিজে আবার ফিরে আসে। সাথে `Chrome_Opener_Shut_Down.py` (সব অ্যাপ বন্ধ করে পিসি শাট ডাউন)।
বিস্তারিত: [`chrome-opener/README.md`](chrome-opener/README.md)

## Claude-এর জন্য নোট
[`NOTES.md`](NOTES.md) — সব সিদ্ধান্ত, সমস্যা ও নিয়ম।
