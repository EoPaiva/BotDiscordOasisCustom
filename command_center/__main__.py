import os

import uvicorn

if __name__ == "__main__":
    uvicorn.run(
        "command_center.app:app",
        host=os.getenv("HOST", "127.0.0.1"),
        port=int(os.getenv("PORT", "8000")),
        reload=False,
        server_header=False,
        timeout_keep_alive=5,
        limit_concurrency=100,
        backlog=128,
    )
