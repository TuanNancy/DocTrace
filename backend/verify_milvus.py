"""
Verify connection to Milvus (chạy khi Docker stack đã up).
"""
from pymilvus import connections, utility  # pyright: ignore[reportMissingImports]

HOST = "localhost"
PORT = 19530


def main():
    print(f"Connecting to Milvus at {HOST}:{PORT} ...")
    try:
        connections.connect(alias="default", host=HOST, port=PORT)
        print("  OK connected.")

        # Server version
        from pymilvus import __version__ as pymilvus_version
        print(f"  pymilvus version: {pymilvus_version}")

        # List collections (có thể rỗng)
        collections = utility.list_collections()
        print(f"  Collections: {collections if collections else '(none)'}")

        connections.disconnect("default")
        print("Disconnected. Milvus connection verified.")
    except Exception as e:
        print(f"  FAIL: {e}")
        raise


if __name__ == "__main__":
    main()
