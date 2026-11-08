"""Sends many submissions at one moment to a running run: the case a deadline creates.

    python -m tools.load_deadline --base https://localhost:18443 --run RUN_ID --clients 50 \\
        --at-epoch SECONDS

`--at-epoch` holds the submissions until that moment: give it a second before the run's deadline.
Each client answers what its page asks, so answers are stored as in real use.

Standard library only. Prints how many were accepted and the slowest answer. The self-signed
certificate of a local deployment is accepted only for localhost.
"""

import argparse
import re
import ssl
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

TOKEN = re.compile(r'name="attempt_token" value="([^"]+)"')
KEY = re.compile(r'name="submission_key" value="([^"]+)"')
ATTEMPT = re.compile(r"/a/([0-9a-f-]{36})/submit")
RADIO = re.compile(
    r'name="([^"]+:options\[\])"[^>]*value="([^"]+)"|value="([^"]+)"[^>]*name="([^"]+:options\[\])"'
)
NUMBER = re.compile(r'name="([^"]+:value)"')
LIMIT_SECONDS = 5.0


def _context(base: str) -> ssl.SSLContext | None:
    host = urllib.parse.urlsplit(base).hostname
    if not base.startswith("https") or host != "localhost":
        return None
    context = ssl.create_default_context()
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    return context


def _post(url: str, fields: dict[str, str], context: ssl.SSLContext | None) -> tuple[int, str]:
    data = urllib.parse.urlencode(fields).encode()
    request = urllib.request.Request(url, data=data, method="POST")  # noqa: S310  # the operator's own address
    try:
        with urllib.request.urlopen(request, context=context, timeout=60) as response:  # noqa: S310
            return response.status, response.read().decode()
    except urllib.error.HTTPError as error:
        return error.code, error.read().decode()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", required=True)
    parser.add_argument("--run", required=True)
    parser.add_argument("--clients", type=int, default=50)
    parser.add_argument("--at-epoch", type=float, default=None)
    args = parser.parse_args()
    context = _context(args.base)
    forms = []
    for _ in range(args.clients):
        status, html = _post(f"{args.base}/r/{args.run}/start", {"lang": "cs"}, context)
        if status != 200:
            print(f"start refused: {status}")
            return 1
        answers = {name: "10" for name in NUMBER.findall(html)}
        for name, value, other_value, other_name in RADIO.findall(html):
            answers.setdefault(name or other_name, value or other_value)
        forms.append(
            (ATTEMPT.findall(html)[0], TOKEN.findall(html)[0], KEY.findall(html)[0], answers)
        )
    if args.at_epoch is not None:
        time.sleep(max(0.0, args.at_epoch - time.time()))
    results: list[tuple[int, float]] = []
    barrier = threading.Barrier(args.clients)

    def submit(attempt: str, token: str, key: str, answers: dict[str, str]) -> None:
        barrier.wait()
        began = time.perf_counter()
        fields = {"attempt_token": token, "submission_key": key, "lang": "cs", **answers}
        status, _html = _post(f"{args.base}/a/{attempt}/submit", fields, context)
        results.append((status, time.perf_counter() - began))

    threads = [threading.Thread(target=submit, args=form) for form in forms]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    accepted = sum(status == 200 for status, _seconds in results)
    slowest = max(seconds for _status, seconds in results)
    print(f"accepted {accepted}, refused {len(results) - accepted}, slowest {slowest:.2f} s")
    return 0 if accepted == args.clients and slowest < LIMIT_SECONDS else 1


if __name__ == "__main__":
    sys.exit(main())
