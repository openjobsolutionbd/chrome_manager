# Only Chrome Opener — পরিবর্তনের ইতিহাস
(নতুনটা উপরে।)

## 1.0.1 — ২০২৬-১১-২৮
- `Chrome_Opener_Shut_Down.py` যোগ হলো: এই সেকশনের নিজস্ব কপি (Chrome জানালা বন্ধ করে পিসি শাট ডাউন)। সেকশনগুলো সম্পূর্ণ স্বাধীন, তাই প্রতিটা সেকশনে নিজের সব ফাইল থাকে।
- কোডের ভার্সন `TOOLKIT_VERSION` 1.0.1।

## 1.0.0 — ২০২৬-১১-২৮
এই রিপোতে প্রথম ভার্সন। আগের আলগা ফাইলের (রিপোতে আসার আগের) তুলনায় পরিবর্তন:
- একসাথে ১০টা প্রোফাইল ব্যাচে খোলে (আগে সর্বোচ্চ ৭টা, একটা একটা করে)।
- প্রতি চক্রে আগে সব খোলা জানালা স্ক্যান হয়, তারপর নতুন ব্যাচ খোলে। আগে প্রতিটা প্রোফাইল খোলার আগে সব উইন্ডো আবার স্ক্যান হতো, যা ধীর ছিল।
- লিমিটের মেসেজের আরও শব্দবন্ধ ধরে ("hit your limit", "reached your limit", "reached your usage limit", "reached the limit", "out of messages", "message limit")।
- Chrome চালুর সময় ৪টা অতিরিক্ত সেটিং: `--force-renderer-accessibility`, `--disable-backgrounding-occluded-windows`, `--disable-renderer-backgrounding`, `--disable-features=CalculateNativeWinOcclusion`।
- ২০ সেকেন্ডের বেশি পড়া না গেলে জানালা অদৃশ্যভাবে সামনে এনে রেন্ডার করায় ("nudge"), ৬০ সেকেন্ডে একবারের বেশি নয়।
- ৫ মিনিট পরপর লগে "Heartbeat" লাইন।
- কোডে `TOOLKIT_VERSION`; শুরুর লগ লাইনে ভার্সন লেখা হয়।
- `Chrome_Opener_Close_All` এই সেকশনে যোগ হলো (Chrome-কে নতুন করে চালু করার জন্য)।
