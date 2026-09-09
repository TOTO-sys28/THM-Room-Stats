# THM Room Stats

A small Flask app that accepts a TryHackMe username **or public profile URL** and displays completed rooms broken down by difficulty.

`tryhackme` `ctf` `pentesting` `flask` `0day`
# Image
<img width="1434" height="784" alt="image" src="https://github.com/user-attachments/assets/11fc326a-a29c-4132-b7c5-5cef8a7ef715" />

## About the TryHackMe API

TryHackMe's current public profile surface is:

```text
GET https://tryhackme.com/api/v2/public-profile?username=<username>
GET https://tryhackme.com/api/v2/public-profile/completed-rooms?username=<username>&limit=50&page=1
```

The completed-rooms response is an object containing `data.docs` and `data.hasNextPage`.

> **Note:** older `/api/all-completed-rooms` examples found online can return HTML instead of JSON, which causes an `invalid JSON` error.

The app sends a standard Chrome browser User-Agent, since TryHackMe's bot mitigation can reject bot-looking clients.

## Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python app.py
```

Then open:

```text
http://127.0.0.1:5000
```

You can input either a username:

```text
0day
```

or a full profile URL:

```text
https://tryhackme.com/p/0day
```

## API

```text
GET /api/stats?username=0day
```

Returns the public profile's level, points, badges, streak, and top-percentage ranking, along with the Easy / Medium / Hard / Insane room completion breakdown.
