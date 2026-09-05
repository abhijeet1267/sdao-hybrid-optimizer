"""Collect a non-secret, read-only provenance manifest for the DB paper."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from hashlib import sha256
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
from typing import Any

from .config import DatabaseConfig
from .connection import connect

ROOT = Path(__file__).resolve().parents[2]

def _command(args: list[str]) -> tuple[str | None, str | None]:
    try:
        result=subprocess.run(args,text=True,capture_output=True,timeout=10,check=True)
        return result.stdout.strip() or None, None
    except (OSError,subprocess.SubprocessError) as exc: return None, f"{type(exc).__name__}: {exc}"

def _sha(path: Path) -> str | None:
    if not path.is_file(): return None
    d=sha256()
    with path.open("rb") as h:
        for block in iter(lambda:h.read(1024*1024),b""): d.update(block)
    return d.hexdigest()

def _package(name: str) -> dict[str, str | None]:
    try: return {"version":importlib.metadata.version(name),"reason":None}
    except importlib.metadata.PackageNotFoundError: return {"version":None,"reason":"not installed"}

def collect() -> dict[str, Any]:
    cpu, cpu_reason=_command(["sysctl","-n","machdep.cpu.brand_string"])
    ram, ram_reason=_command(["sysctl","-n","hw.memsize"])
    if cpu is None: cpu=platform.processor() or None
    if ram is not None: ram=str(int(ram)//(1024**2))+" MiB"
    docker_version,docker_reason=_command(["docker","version","--format","{{.Server.Version}}"])
    image_digest,image_reason=_command(["docker","image","inspect","pgvector/pgvector:0.8.5-pg16","--format","{{index .RepoDigests 0}}"])
    git_commit,git_reason=_command(["git","rev-parse","HEAD"])
    git_root, _=_command(["git","rev-parse","--show-toplevel"])
    db={"server_version":None,"pgvector_version":None,"reason":None}
    try:
        cfg=DatabaseConfig.from_env(); con=connect(cfg)
        try:
            with con.cursor() as cur:
                cur.execute("SHOW server_version"); db["server_version"]=str(cur.fetchone()[0])
                cur.execute("SELECT extversion FROM pg_extension WHERE extname = 'vector'"); row=cur.fetchone(); db["pgvector_version"]=None if row is None else str(row[0])
            db.update({"host":cfg.host,"port":cfg.port,"database":cfg.database,"user":cfg.user})
        finally: con.close()
    except Exception as exc: db["reason"]=f"{type(exc).__name__}: {exc}"
    base=ROOT/"dataset/sift/sift_base.fvecs"; attrs=ROOT/"attributes.csv"; queries=ROOT/"queries.csv"
    package_names=["psycopg","pandas","numpy","matplotlib","scikit-learn","python-dotenv","PyPDF2"]
    return {"collected_at_utc":datetime.now(timezone.utc).isoformat(),"collection_scope":"read-only; excludes passwords and secrets",
      "hardware":{"cpu_model":cpu,"cpu_model_reason":cpu_reason,"architecture":platform.machine(),"logical_cpu_count":os.cpu_count(),"ram":ram,"ram_reason":ram_reason},
      "operating_system":{"name":platform.system(),"version":platform.version(),"release":platform.release()},
      "python":{"version":sys.version,"executable":sys.executable,"prefix":sys.prefix,"virtual_env":os.environ.get("VIRTUAL_ENV")},
      "packages":{name:_package(name) for name in package_names},
      "docker":{"server_version":docker_version,"server_version_reason":docker_reason,"image":"pgvector/pgvector:0.8.5-pg16","image_digest":image_digest,"image_digest_reason":image_reason},
      "postgresql":db,
      "dataset":{"name":"SIFT1M","row_count":1_000_000,"embedding_dimension":128,"base_vectors_path":str(base.relative_to(ROOT)),"base_vectors_sha256":_sha(base),"attributes_path":str(attrs.relative_to(ROOT)),"attributes_sha256":_sha(attrs)},
      "queries":{"path":str(queries.relative_to(ROOT)),"sha256":_sha(queries),"query_count":32,"generator":"generate_queries.py","seed":42,"seed_source":"np.random.seed(42) in generate_queries.py"},
      "git":{"git_repository":git_root is not None,"git_commit":git_commit if git_root else None,"reason":None if git_root else git_reason}}

def main() -> None:
    parser=argparse.ArgumentParser(description="Collect DB-paper provenance without modifying database state")
    parser.add_argument("--output",type=Path,required=True); args=parser.parse_args()
    if args.output.exists(): raise FileExistsError(f"provenance output exists: {args.output}")
    args.output.parent.mkdir(parents=True,exist_ok=True); args.output.write_text(json.dumps(collect(),indent=2)+"\n")
    print(f"Wrote provenance manifest to {args.output}")
if __name__ == "__main__": main()
