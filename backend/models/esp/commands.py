from pydantic import BaseModel

class ESPCommand(BaseModel):
    type: str = "command"
    name: str
    payload: dict
