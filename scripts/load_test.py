import httpx
import asyncio
import time

API_URL = "http://localhost:8000/api/v1/jobs"

async def submit_job(client: httpx.AsyncClient, i: int):
    """Submit a single job and print the result."""
    payload = {
        "job_type": "csv",
        "payload": {
            "filename": f"load_test_{i}.csv",
            "operations": ["row_count", "column_stats"]
        }
    }
    try:
        response = await client.post(API_URL, json=payload, timeout=10)
        print(f"Job {i}: {response.status_code} - {response.json().get('id')}")
    except Exception as e:
        print(f"Job {i} failed: {e}")

async def main():
    print("Starting load test — submitting 50 jobs...")
    start = time.time()

    async with httpx.AsyncClient() as client:
        tasks = [submit_job(client, i) for i in range(50)]
        await asyncio.gather(*tasks)

    elapsed = time.time() - start
    print(f"\nDone. 50 jobs submitted in {elapsed:.2f} seconds")

if __name__ == "__main__":
    asyncio.run(main())