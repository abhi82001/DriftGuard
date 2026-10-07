from __future__ import annotations
from dataclasses import dataclass
import hashlib, pathlib, zipfile
@dataclass(frozen=True)
class UploadInspection: safe:bool; reason:str; sha256:str

def inspect_upload(path, *, max_bytes=50_000_000, max_zip_members=5000, max_uncompressed=250_000_000):
    p=pathlib.Path(path); size=p.stat().st_size; digest=hashlib.sha256(p.read_bytes()).hexdigest()
    if size>max_bytes:return UploadInspection(False,"file too large",digest)
    if zipfile.is_zipfile(p):
        with zipfile.ZipFile(p) as z:
            infos=z.infolist()
            if len(infos)>max_zip_members:return UploadInspection(False,"too many archive members",digest)
            if sum(i.file_size for i in infos)>max_uncompressed:return UploadInspection(False,"archive expands beyond limit",digest)
            for i in infos:
                parts=pathlib.PurePosixPath(i.filename).parts
                if ".." in parts or i.filename.startswith(("/","\\")): return UploadInspection(False,"unsafe archive path",digest)
    return UploadInspection(True,"accepted",digest)
