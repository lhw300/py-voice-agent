# web/auth_router.py  —— 登录认证路由
# main.py 里 include: app.include_router(auth_router.router)

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
import secrets
import binascii
import logging
from Crypto.Cipher import DES3
import pymysql
import redis as redislib
import ai_config as AiConfig

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api")

_DES_KEY      = "G1 www.it9000.cn Nanjing"
_TOKEN_EXPIRE = 8 * 3600
_token_redis  = None


def _get_token_redis():
    global _token_redis
    if _token_redis is None:
        host = AiConfig.getStringConfig("redis.host", "localhost")
        port = AiConfig.getIntConfig("redis.port",    6379)
        db   = AiConfig.getIntConfig("redis.db",      0)
        _token_redis = redislib.Redis(host=host, port=port, db=db)
    return _token_redis


def _get_mysql():
    return pymysql.connect(
        host     = AiConfig.getStringConfig("db.mysql.host",     "localhost"),
        port     = AiConfig.getIntConfig   ("db.mysql.port",     3306),
        user     = AiConfig.getStringConfig("db.mysql.user",     "root"),
        password = AiConfig.getStringConfig("db.mysql.password", "lcall"),
        database = AiConfig.getStringConfig("db.mysql.dbname",   "vsale"),
        charset  = "utf8mb4",
    )


def _encrypt_password(passwd: str) -> str:
    key_bytes    = _DES_KEY.encode()
    passwd_bytes = passwd.encode()
    pad_len      = 8 - (len(passwd_bytes) % 8)
    passwd_bytes += bytes([pad_len] * pad_len)
    cipher    = DES3.new(key_bytes, DES3.MODE_ECB)
    encrypted = cipher.encrypt(passwd_bytes)
    return binascii.hexlify(encrypted).upper().decode()


def _validate_pwd(passwd: str, db_passwd: str) -> bool:
    if not passwd or not db_passwd:
        return False
    if db_passwd.startswith("UNENCRYPT"):
        return passwd == db_passwd[9:]
    return _encrypt_password(passwd) == db_passwd.replace(":", "").upper()


# ── Pydantic models ───────────────────────────────────────────────────────────

class LoginRequest(BaseModel):
    id_oper: str
    passwd:  str

class TokenRequest(BaseModel):
    token: str


# ── Routes ────────────────────────────────────────────────────────────────────

@router.get("/auth/config")
def auth_config():
    dev_mode = AiConfig.getStringConfig("admin.dev.mode", "false").lower() == "true"
    return {"dev_mode": dev_mode}


@router.post("/auth/login")
def login(body: LoginRequest):
    allowed = AiConfig.getStringConfig("admin.id_oper", "1000")
    if body.id_oper != allowed:
        raise HTTPException(401, "工号无权限")

    conn = _get_mysql()
    try:
        with conn.cursor(pymysql.cursors.DictCursor) as cur:
            cur.execute(
                "SELECT id_oper, code_oper, passwd, id_valid FROM dm_oper WHERE id_oper=%s",
                (body.id_oper,)
            )
            row = cur.fetchone()
    finally:
        conn.close()

    if not row:
        raise HTTPException(401, "工号不存在")
    if str(row["id_valid"]) != "0":
        raise HTTPException(401, "工号已注销")
    if not _validate_pwd(body.passwd, row["passwd"]):
        raise HTTPException(401, "密码错误")

    token = secrets.token_hex(32)
    _get_token_redis().set(f"admin_token:{token}", body.id_oper, ex=_TOKEN_EXPIRE)

    logger.info(f"✅ login success id_oper={body.id_oper}")
    return {
        "token":     token,
        "id_oper":   body.id_oper,
        "code_oper": row.get("code_oper", ""),
    }


@router.post("/auth/logout")
def logout(body: TokenRequest):
    _get_token_redis().delete(f"admin_token:{body.token}")
    return {"ok": True}


@router.get("/auth/check")
def check_token(token: str):
    id_oper = _get_token_redis().get(f"admin_token:{token}")
    if not id_oper:
        raise HTTPException(401, "token 无效或已过期")
    return {"valid": True, "id_oper": id_oper.decode()}
