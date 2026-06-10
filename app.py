import asyncio
from flask import Flask, request, jsonify, render_template
from scraper import UberEatsScraper

app = Flask(__name__)

def run_async(coro):
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/api/scrape", methods=["POST"])
def scrape():
    data = request.get_json()
    query = data.get("query", "").strip()
    url = data.get("url", "").strip()
    debug = data.get("debug", False)
    max_stores = data.get("max_stores", 20)

    if not query and not url:
        return jsonify({"error": "Enter a location or Uber Eats URL"}), 400

    scraper = UberEatsScraper(headless=True, debug=debug)

    try:
        if url:
            results = run_async(scraper.scrape_restaurant_url(url))
        else:
            results = run_async(scraper.scrape_location(query, max_stores=max_stores))

        return jsonify({
            "results": results,
            "count": len(results),
            "query": query or url,
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/feed", methods=["POST"])
def feed():
    data = request.get_json()
    query = data.get("query", "").strip()
    debug = data.get("debug", False)

    if not query:
        return jsonify({"error": "Enter a location"}), 400

    scraper = UberEatsScraper(headless=True, debug=debug)

    try:
        stores = run_async(scraper.scrape_feed(query))
        return jsonify({
            "stores": stores,
            "count": len(stores),
            "query": query,
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/store_items", methods=["POST"])
def store_items():
    data = request.get_json()
    url = data.get("url", "").strip()
    debug = data.get("debug", False)

    if not url:
        return jsonify({"error": "Store URL is required"}), 400

    scraper = UberEatsScraper(headless=True, debug=debug)

    try:
        items = run_async(scraper.scrape_store_items(url))
        return jsonify({
            "items": items,
            "count": len(items),
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/scrape_restaurant", methods=["POST"])
def scrape_restaurant():
    data = request.get_json()
    url = data.get("url", "").strip()
    debug = data.get("debug", False)

    if not url:
        return jsonify({"error": "Uber Eats restaurant URL is required"}), 400

    scraper = UberEatsScraper(headless=True, debug=debug)

    try:
        results = run_async(scraper.scrape_restaurant_url(url))
        return jsonify({
            "results": results,
            "count": len(results),
            "url": url,
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
