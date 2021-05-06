from threading import Thread, Timer
import time
from sdk.core import auth, login, get_user, send_text, ensure_direct_chat
from sdk.messaging import Context, connect, set_request_handler
from game import Game, TEXT_INTRO_PART_A, TEXT_INTRO_PART_B, Identity
import random
from enum import Enum
from config import countryCode, mobile, password
import traceback

''' 枚举定义 '''
class CurrentState(Enum):
    NOT_STARTED = 0
    TALKING = 1
    VOTING = 2
    HEARTBEATING = 3


''' 全局变量和常量 '''
MIN_PLAYERS = 6
current_state = CurrentState.NOT_STARTED
playing_games: dict[str, Game] = {}
timer = None

''' 通用实用功能 开始 '''


def get_nickname(user_id: str) -> str:
    return get_user(user_id).nickname


def get_nicknames(user_ids: list[str]) -> str:
    return ", ".join(map(lambda user_id: get_nickname(user_id), user_ids))


''' 通用实用功能 结束 '''


''' 游戏系统外控制功能 开始 '''


def has_game(ctx: Context):
    return ctx.chat.id in playing_games


def create_game(ctx: Context, dataset: str):
    owner_id = ctx.message.from_user_id
    game_id = ctx.chat.id

    playing_games[game_id] = Game(dataset, owner_id)

    print("- created game: %s" % game_id)


''' 游戏系统外控制功能 结束 '''

class GameEnded(Exception):
    def __init__(self):
        pass


class GameContext:
    ctx: Context
    game: Game
    game_id: str
    # 游戏类被创建

    def __init__(self, ctx: Context) -> None:
        self.ctx = ctx
        self.game = playing_games.get(ctx.chat.id)
        self.game_id = ctx.chat.id

    ''' 多使用情形型功能 开始 '''
    # 清除所有计时器。使用情形：一个回合结束时；游戏结束时。

    # 对游戏是否需要终止的判断。使用情形：每回合的结束；有玩家主动退出游戏；有玩家违反规则被退出游戏时。

    def check_ending(self):
        undercover_id = ""
        for p in self.game.user_info_map.keys():
            if self.game.user_info_map[p]["identity"] == Identity.UNDERCOVER:
                undercover_id = p
        if undercover_id == "":
            self.end_game(message="群众获得了胜利，游戏结束！")
        if len(self.game.user_ids()) <= 2:
            undercover_name = get_nickname(undercover_id)
            self.end_game(message="恭喜 "+undercover_name +
                          " 获得胜利，游戏结束～"+undercover_name+" 的身份是卧底")
        return False
    ''' 多使用情形型功能 结束 '''

    ''' 一个完整的回合 开始 '''
    # 开始新一回合

    def start_new_talk(self):
        self.check_ending()
        self.ctx.send_text("新一回合开始了！请大家描述你收到的词语。当前仍然存活的玩家：%s" %
                           get_nicknames(self.game.user_ids()))
        globals()['current_state'] = CurrentState.TALKING

    def kick_not_answered_players(self):
        dead_players = self.game.not_answered_user_ids()
        for p in dead_players:
            if p in self.game.user_info_map:
                self.game.user_info_map.pop(p)
                nickname = get_nickname(p)
                self.ctx.send_text("玩家 %s 因未进行描述而被移出游戏" % nickname)

    # 从描述词语状态切换到投票状态
    def alter_to_vote(self):
        # 踢掉不进行“描述”的玩家
        self.game.answered_user_ids = []
        is_ended = self.check_ending()
        if not is_ended:
            ls = []
            for p in self.game.user_info_map.keys():
                ls.append((self.game.user_info_map[p]["id"], p))
            ls.sort()
            str_ls = "现在进入投票环节，下面是玩家编号列表："
            for item in ls:
                str_ls += "\n%d - %s" % (item[0], get_nickname(item[1]))
            self.ctx.send_text(str_ls)
            globals()['current_state'] = CurrentState.VOTING

    # 投票结束，切换到回合结算状态

    def finish_vote(self):
        max_ones = []
        max_poll = -1
        # 找出票数最多的同志，然后杀死这位同志
        for p in self.game.user_ids():
            if self.game.user_info_map[p]["poll"] > max_poll:
                max_ones = [p]
                max_poll = self.game.user_info_map[p]["poll"]
            elif self.game.user_info_map[p]["poll"] == max_poll:
                max_ones.append(p)
        # 再把所有人的票数初始为0，设所有人为“未投票”状态
        for p in self.game.user_ids():
            self.game.user_info_map[p]["poll"] = 0
            self.game.voted_user_ids = []
        if len(max_ones)==1:
            dead_one=max_ones[0]
            self.ctx.send_text("%s 获得的票数最多，离开了游戏" % get_nickname(dead_one))
            self.game.leave(dead_one)
            globals()["current_state"] = CurrentState.HEARTBEATING
            self.check_ending()
            self.ctx.send_text("投票结束，现在不要发送消息！")
            return True
        else:
            return False


    # 结算旧的回合，开始新的回合
    def game_thread(self):
        try:
            while True:
                self.start_new_talk()
                time.sleep(60)
                self.kick_not_answered_players()
                vote_success=False
                first_round=True
                while not vote_success:
                    if not first_round:
                        self.ctx.send_text("有2人票数相等，开启重新计票！")
                    else:
                        first_round=False
                    self.alter_to_vote()
                    time.sleep(60)
                    vote_success=self.finish_vote()
                time.sleep(3)
                self.check_ending()
        except Exception:
            traceback.print_exc()

    ''' 一个完整的回合 结束 '''

    ''' 游戏系统内控制功能 开始 '''
    # 开始游戏：分配身份

    def start_game(self):
        if self.game.is_started: return
        if len(self.game.user_ids()) < MIN_PLAYERS:
            return

        # 向大家发送开始游戏的消息
        nicknames = get_nicknames(self.game.user_ids())
        self.ctx.send_text("游戏现在开始，参与玩家：%s" % nicknames)

        # 游戏进入启动状态，开始第一个回合
        self.game.is_started = True

        # 给每个玩家分配身份和词语，并私聊告知
        undercover_player = random.choice(
            list(self.game.user_info_map))  # 随机钦定一个卧底玩家
        for player in self.game.user_info_map.keys():
            private_chat = ensure_direct_chat(player)
            if not player == undercover_player:
                self.game.user_info_map[player]["identity"] = Identity.COMMON
                send_text(private_chat.id, "你的身份是平民，抽到的词语是" +
                          self.game.word_pair["w1"])
            else:
                self.game.user_info_map[undercover_player]["identity"] = Identity.UNDERCOVER
                send_text(private_chat.id, "你的身份是卧底，抽到的词语是" +
                          self.game.word_pair["w2"])
        # 启动游戏
        t = Thread(target=self.game_thread)
        t.start()
        print("- started game: %s" % self.game_id)

    # 结束游戏
    def end_game(self, message: str = "游戏结束"):
        self.game.is_started = False
        if self.game_id in playing_games:  # TODO：出现了game_id意外失踪的情况
            playing_games.pop(self.game_id)

        self.ctx.send_text(message)
        print("- ended game: %s" % self.game_id)
        self.game.is_started=False
        globals()['current_state'] = CurrentState.NOT_STARTED
        raise GameEnded
    ''' 游戏系统内控制功能 结束 '''



def request_handler(ctx: Context):
    global current_state
    ''' 消息合法性判断 '''
    message = ctx.message
    # 获得发送者用户ID
    current_user_id = message.from_user_id

    # 如果不是普通玩家发送的消息，则不再继续处理
    if message.from_user_id is None or message.from_user_id == auth.user.id:
        return

    # 如果消息不是文本，则不再继续处理
    if message.type != "text":
        return

    ''' 游戏对象存在性判断 '''
    # 创建游戏对象
    if message.content == "谁是卧底":
        if has_game(ctx):
            return

        create_game(ctx, "sswd")

        game_ctx = GameContext(ctx)
        game_ctx.game.join(current_user_id)  # 让创建者进入游戏

        # 2分钟后自动开始或结束
        timer = Timer(120, lambda: start_or_end_game())
        timer.start()
        
        # 游戏启动，发送游戏规则
        ctx.send_text(TEXT_INTRO_PART_A)
        ctx.send_text(TEXT_INTRO_PART_B)
        ctx.send_text("系统将等待 2 分钟，如果创建者没有发出开始或结束指令，将自动开始或取消游戏。")

    # 如果无游戏对象，则不再继续处理
    if not has_game(ctx):
        return

    ''' 游戏系统内操作处理 '''
    game_ctx = GameContext(ctx)
    game = game_ctx.game

    # 依据人数自动决定是开始还是不开始游戏，是2分钟计时器结束时的回调函数
    def start_or_end_game():
        global timer
        if timer is not None:
            timer.cancel()
        timer=None
        if len(game.user_ids()) < MIN_PLAYERS:
            return game_ctx.end_game(message="由于少于 %d 人参与，游戏未能成功开始" % MIN_PLAYERS)
        game_ctx.start_game()

    nickname = get_nickname(current_user_id)
    if not game.is_started:
        if message.content == "加入":
            if current_user_id not in game.user_info_map.keys():
                game.join(current_user_id)
                ctx.send_text("%s 加入了游戏" % get_nickname(current_user_id))

        elif message.content == "退出":
            game.leave(current_user_id)
            ctx.send_text("%s 退出了游戏" % get_nickname(current_user_id))

        elif message.content == "玩家列表":
            ctx.send_text("参与玩家：%s" % get_nicknames(game.user_ids()))

        elif message.content == "结束" and game.is_owned_by(current_user_id):
            game_ctx.end_game(message="创建者取消了这局游戏～")

        elif message.content == "开始" and game.is_owned_by(current_user_id):
            if len(game.user_ids()) < MIN_PLAYERS:
                return ctx.send_text("至少 %d 人参与才能开始游戏" % MIN_PLAYERS)
            game_ctx.start_game()
    elif message.content == "结束" and game.is_owned_by(current_user_id):
        game_ctx.end_game(message="创建者结束了游戏～")
    elif current_user_id in game.user_ids():  # 已经开始了游戏，且发消息的玩家在玩家列表里
        if message.content == "退出":
            # 移除这个玩家
            game.leave(current_user_id)
            # 发送消息
            nickname = get_nickname(current_user_id)
            ctx.send_text("%s 中途退出了游戏～" % nickname)
            # 看看游戏是否因这个玩家的退出结束
            game_ctx.check_ending()
        else:  # 已经开始了游戏，且发消息的玩家在玩家列表里，且不是“退出”
            ''' 玩家参与性操作处理（游戏系统内操作处理的一部分） 开始 '''
            if current_state == CurrentState.TALKING:  # 作答时间段内
                # 如果检测到该用户本轮已经发过言还发言，则将其踢出
                if current_user_id not in game.answered_user_ids:
                    game.answered_user_ids.append(current_user_id)
                else:
                    game.leave(current_user_id)
                    ctx.send_text("%s 因在本轮发言次数超过一次而被移出游戏" % nickname)
            elif current_state == CurrentState.VOTING:  # 投票时间段内
                if current_user_id not in game.voted_user_ids:
                    game.voted_user_ids.append(current_user_id)
                    try:
                        ballot = int(message.content)
                        for p in game.user_info_map.keys():
                            if game.user_info_map[p]["id"] == ballot:  # 找到对应的玩家
                                game.user_info_map[p]["poll"] += 1
                                ctx.send_text("%s 把票投给了 %s" %
                                              (nickname, get_nickname(p)))
                                break
                    except Exception:
                        ctx.send_text("%s 没有输入正确的玩家序号，视为本次弃权" % nickname)
                else:
                    game.leave(current_user_id)
                    nickname = get_nickname(current_user_id)
                    ctx.send_text("%s 因在本轮投票次数超过一次而被移出游戏" % nickname)
            elif current_state == CurrentState.HEARTBEATING:
                game.leave(current_user_id)
                nickname = get_nickname(current_user_id)
                ctx.send_text("%s 因在规定时间段外发送消息被移出游戏" % nickname)
            ''' 玩家参与性操作处理（游戏系统内操作处理的一部分） 结束 '''



set_request_handler(request_handler)

login(countryCode, mobile, password)

connect()
