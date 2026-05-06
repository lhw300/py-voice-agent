from pydantic import BaseModel

class EivrRequest(BaseModel):
    sn:         str   # 通话唯一流水号
    crid:       str   # 本次请求ID
    ch:         str   # 通道
    call_date:  str
    start_time: str
    phone:      str
    vo_id:      str   # 路由标识
    text:       str   # 客户说的话

class EivrResponse(BaseModel):
    code:   int        # 0=成功 -1=失败
    answer: str        # AI回复内容
    action: str = ""   # 动作码，对应Java的ChatAnswer.action
