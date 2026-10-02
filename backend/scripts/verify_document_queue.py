"""Exercise the real migration/leases/RLS in disposable PostgreSQL, without cloud keys.

Run from backend/: python scripts/verify_document_queue.py (Docker required).
"""
import json
from pathlib import Path
import subprocess
import time
import uuid


def main():
    name = f"baymax-queue-test-{uuid.uuid4().hex[:10]}"

    def sql(statement, *, fails=False):
        result = subprocess.run(
            ["docker", "exec", "-i", name, "psql", "-U", "postgres", "-At", "-v", "ON_ERROR_STOP=1"],
            input=statement, text=True, capture_output=True,
        )
        if fails:
            assert result.returncode != 0, "SQL unexpectedly succeeded"
            return result.stderr
        if result.returncode:
            raise RuntimeError(result.stderr)
        return result.stdout.strip()

    def claim():
        value = sql("select claim_document_job(120);")
        return json.loads(value) if value else None

    def finish(job, error="null"):
        return sql(f"select finish_document_job('{job['job_id']}', '{job['lease_token']}', {error}, 3, '[]');")

    try:
        subprocess.run(["docker", "run", "-d", "--rm", "--name", name, "--network", "none",
                        "-e", "POSTGRES_HOST_AUTH_METHOD=trust", "postgres:16-alpine"], check=True, capture_output=True)
        for _ in range(60):
            ready = subprocess.run(["docker", "exec", name, "pg_isready", "-U", "postgres"], capture_output=True)
            if ready.returncode == 0:
                break
            time.sleep(0.5)
        else:
            raise RuntimeError("PostgreSQL did not start")
        sql("""
            create schema auth;
            create table auth.users(id uuid primary key);
            create role anon; create role authenticated; create role service_role bypassrls;
            create function auth.uid() returns uuid language sql stable as
            $$ select nullif(current_setting('request.jwt.claim.sub', true), '')::uuid $$;
            grant usage on schema auth, public to authenticated, anon, service_role;
        """)
        sql((Path(__file__).resolve().parents[1] / "migrations/001_document_library.sql").read_text())
        owner, other, doc = [str(uuid.uuid4()) for _ in range(3)]
        sql(f"insert into auth.users values ('{owner}'), ('{other}');")
        sql(f"insert into documents(doc_id,user_id,name,size_bytes,storage_key) values ('{doc}','{owner}','file.pdf',20,'owner/doc/file.pdf');")
        assert "Document not found" in sql(f"select queue_document_job('{doc}','{other}','index');", fails=True)
        sql(f"select queue_document_job('{doc}','{owner}','index');")
        first = claim()
        assert first["document"]["status"] == "processing"
        assert sql(f"select heartbeat_document_job('{first['job_id']}','{first['lease_token']}',120);") == "t"
        assert claim() is None, "An unexpired claim must not be delivered twice"
        sql(f"update document_jobs set lease_expires_at = now() - interval '1 second' where job_id = '{first['job_id']}';")
        second = claim()
        assert second["attempts"] == 2
        assert second["lease_token"] != first["lease_token"]
        assert len(second["generations"]) == 2
        assert sql(f"select heartbeat_document_job('{first['job_id']}','{first['lease_token']}',120);") == "f"
        assert finish(first) == "f", "A stale worker must not publish"
        assert finish(second) == "t"
        assert sql(f"select active_index_id from documents where doc_id = '{doc}';") == second["lease_token"]

        # Real RLS and function privileges, not a Python approximation.
        mine = sql(f"set role authenticated; set request.jwt.claim.sub = '{owner}'; select count(*) from documents;")
        theirs = sql(f"set role authenticated; set request.jwt.claim.sub = '{other}'; select count(*) from documents;")
        assert mine.splitlines()[-1] == "1" and theirs.splitlines()[-1] == "0"
        assert "permission denied" in sql("set role authenticated; select claim_document_job(120);", fails=True)
        assert "permission denied" in sql("set role authenticated; select * from document_jobs;", fails=True)
        assert "permission denied" in sql("set role authenticated; update documents set status='ready';", fails=True)

        # Deletion clears the published pointer immediately and retries cleanup.
        sql(f"select queue_document_job('{doc}','{owner}','delete');")
        assert sql(f"select active_index_id is null from documents where doc_id='{doc}';") == "t"
        deletion = claim()
        assert deletion["kind"] == "delete"
        assert finish(deletion, "'Storage temporarily unavailable'") == "f"
        assert sql(f"select status from documents where doc_id='{doc}';") == "delete_error"
        sql(f"select queue_document_job('{doc}','{owner}','index');", fails=True)
        sql(f"select queue_document_job('{doc}','{owner}','delete');")
        assert finish(claim()) == "t"
        assert sql(f"select status from documents where doc_id='{doc}';") == "deleted"
        assert sql(f"set role authenticated; set request.jwt.claim.sub = '{owner}'; select count(*) from documents;").splitlines()[-1] == "0"

        # A delete requested during indexing waits for the active writer, and that
        # writer cannot publish after the tombstone has been installed.
        doc2 = str(uuid.uuid4())
        sql(f"insert into documents(doc_id,user_id,name,size_bytes,storage_key) values ('{doc2}','{owner}','b.pdf',20,'b.pdf');")
        sql(f"select queue_document_job('{doc2}','{owner}','index');")
        indexing = claim()
        sql(f"select queue_document_job('{doc2}','{owner}','delete');")
        assert claim() is None
        assert finish(indexing) == "f"
        assert finish(claim()) == "t"

        # Bounded restart recovery and stale upload recovery.
        doc3 = str(uuid.uuid4())
        sql(f"insert into documents(doc_id,user_id,name,size_bytes,storage_key) values ('{doc3}','{owner}','c.pdf',20,'c.pdf');")
        sql(f"select queue_document_job('{doc3}','{owner}','index');")
        interrupted = claim()
        sql(f"update document_jobs set attempts=3, lease_expires_at=now()-interval '1 second' where job_id='{interrupted['job_id']}';")
        assert claim() is None
        assert sql(f"select status from documents where doc_id='{doc3}';") == "error"
        sql(f"select queue_document_job('{doc3}','{owner}','index');")
        assert claim()["attempts"] == 1
        doc4 = str(uuid.uuid4())
        sql(f"insert into documents(doc_id,user_id,name,size_bytes,storage_key,updated_at) values ('{doc4}','{owner}','d.pdf',20,'d.pdf',now()-interval '16 minutes');")
        claim()
        assert sql(f"select status from documents where doc_id='{doc4}';") == "error"
        print("Document queue: migration, RLS, leases, recovery, deletion and fencing passed.")
    finally:
        subprocess.run(["docker", "rm", "-f", name], capture_output=True)


if __name__ == "__main__":
    main()
