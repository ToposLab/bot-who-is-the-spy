import json
import os
from enum import Enum
import random
TEXT_INTRO_PART_A = """欢迎来到谁是卧底，让我来简单介绍一下操作方式吧！

=== 当前可输入指令 ===
加入 -> 加入游戏
退出 -> 退出游戏
玩家列表 -> 查看玩家列表

=== 游戏进行中的指令 ===
退出 -> 直接自动被淘汰

=== 游戏创建者可用指令 ===
开始 -> 开始游戏
结束 -> 立即结束游戏"""

TEXT_INTRO_PART_B = """=== 游戏玩法 ===
当所有玩家就绪后，由管理员宣布游戏开始。
游戏开始后每人每轮用一句话来描述自己拿到的词语，既不能让卧底察觉，也要给同伴以暗示。
一轮结束后所有人投票，票数最多的人出局。
如果被出局的人是卧底，游戏结束，群众获胜；否则游戏继续。
当场上只剩下3人，且其中有1人是卧底时，游戏结束，卧底获胜。
注意事项：
1) 每个人在30秒的作答时间段内必须发送且只能发送一条消息。
2) 每个人在60秒的投票时间段内最多进行一次投票。
3) 在游戏过程中，不可以在以上时间段外发送除“退出”以外的任何消息。
4) 在游戏过程中，不可以发送非文本消息。
5) 在投票过程中，不输入正确的玩家序号视为放弃本轮投票。
6) 违反游戏规则1,2,3,4将会被机器人请出局！请大家配合。
"""

class Identity(Enum):
    NONE = 0
    UNDERCOVER = 1
    COMMON = 2


class Game:
    is_started: bool
    owner_id: str
    user_info_map: dict[str, dict]
    answered_user_ids: list
    voted_user_ids: list
    word_pair: dict[str, str]
    player_count: int

    def __init__(self, dataset: str, owner_id: str):
        with open(os.getcwd() + '/dataset/%s.json' % dataset, encoding="utf-8") as f:
            data = json.load(f)
            self.word_pair = random.choice(data)
        self.is_started = False
        self.owner_id = owner_id
        self.user_info_map = {}
        self.answered_user_ids=[]
        self.voted_user_ids=[]
        self.player_count=0

    def get_identity_name(self,identity):
        if identity==0: return "无"
        elif identity==1: return "卧底"
        elif identity==2: return "平民"

    def is_owned_by(self, user_id: str):
        return self.owner_id == user_id

    def user_ids(self):
        return list(self.user_info_map.keys())

    def join(self, user_id: str):
        self.player_count+=1
        self.user_info_map[user_id] = {"identity": Identity.NONE, "id": self.player_count, "poll": 0}

    def leave(self, user_id: str):
        self.user_info_map.pop(user_id)

    def not_answered_user_ids(self):
        return list(set(self.user_ids())-set(self.answered_user_ids))
