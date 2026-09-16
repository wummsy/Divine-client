"""Post an announcement to the Divine Client news feed from the command line.

Two ways to use it:

  1) Locally on the server (writes straight to the database):
         python3 post_news.py --title "1.1 is out" --body "Bug fixes and speed."

  2) Remotely over HTTP (needs ADMIN_KEY and the server running):
         python3 post_news.py --url https://divineclient.wispbyte.org \
             --key YOUR_ADMIN_KEY \
             --title "1.1 is out" --body "Bug fixes and speed." --tag Release

Whatever you post shows up in the launcher's LATEST NEWS panel (newest first)
the next time it refreshes.
"""
import argparse
import sys


def main():
    ap = argparse.ArgumentParser(description="Post an Divine Client announcement.")
    ap.add_argument("--title", required=True)
    ap.add_argument("--body", default="")
    ap.add_argument("--tag", default="Update")
    ap.add_argument("--link", default="", help="optional 'Read more' URL")
    ap.add_argument("--url", default="", help="server base URL for remote posting")
    ap.add_argument("--key", default="", help="ADMIN_KEY for remote posting")
    args = ap.parse_args()

    if args.url:
        import requests
        r = requests.post(args.url.rstrip("/") + "/api/announcements", json={
            "title": args.title, "body": args.body,
            "tag": args.tag, "url": args.link, "key": args.key,
        }, timeout=20)
        if r.ok and r.json().get("ok"):
            print("Posted. id =", r.json().get("id"))
        else:
            print("Failed:", r.status_code, r.text)
            sys.exit(1)
    else:
        import envfile  # noqa: F401  (loads .env so DIVINE_DB is set)
        import db
        db.init_db()
        ann_id = db.add_announcement(args.title, args.body, args.tag, args.link)
        print("Posted locally. id =", ann_id)


if __name__ == "__main__":
    main()
