"""
skill_review_system.py — GA间隔复习系统 (SpacedRepetition)

基于艾宾浩斯遗忘曲线的技能复习引擎:
  初次 → 1天 → 3天 → 7天 → 14天 → 30天

核心设计:
  1. CardSet: 一个技能包/文档对应一组复习卡片
  2. 每张卡片含: 知识点(问) + 答案要点(答) + 掌握度(0-5) + 下次复习时间
  3. 每日复习: daemon定时触发，选今天到期的卡片
  4. 掌握度越高，间隔越长（SM-2算法简化版）

快速开始:
  from skill_review_system import ReviewMaster
  master = ReviewMaster()
  master.daily_review()  # 每日复习
  master.scan_all()      # 扫描所有知识点生成卡片
"""

import os
import sys
import json
import time
import hashlib
from pathlib import Path
from datetime import datetime, timedelta, date
from typing import List, Dict, Optional, Any, Tuple
from dataclasses import dataclass, field, asdict

# ─── 路径 ─────────────────────────────────────────
GA_ROOT = Path(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
REVIEW_DIR = GA_ROOT / "data" / "review_cards"
REVIEW_DIR.mkdir(parents=True, exist_ok=True)

SKILL_DIR = Path(r"E:\my-agent_Workspace\ai skill\ai skill")
if not SKILL_DIR.exists():
    SKILL_DIR = GA_ROOT.parent / "ai skill" / "ai skill"


# ═══════════════════════════════════════════════════
# 卡片数据模型
# ═══════════════════════════════════════════════════

@dataclass
class ReviewCard:
    """一张复习卡片"""
    id: str                              # hash(content + source)
    source: str                          # 来源（技能包名/文档名）
    source_type: str                     # skill/doc/ppt/pdf
    category: str                        # 分类（思维模型/技术/运营/...）
    question: str                        # 知识点问题
    answer: str                          # 答案要点
    hint: str = ""                       # 提示（可选）
    mastery: int = 0                     # 0=未学 1=模糊 2=印象 3=理解 4=熟练 5=本能
    interval_days: int = 1               # 当前间隔（天）
    next_review: str = ""                # 下次复习日期 (YYYY-MM-DD)
    last_review: str = ""                # 上次复习日期
    review_count: int = 0                # 复习次数
    created: str = ""                    # 创建时间
    tags: List[str] = field(default_factory=list)

    def __post_init__(self):
        if not self.created:
            self.created = datetime.now().strftime("%Y-%m-%d %H:%M")
        if not self.next_review:
            self.next_review = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")

    def to_dict(self) -> dict:
        return asdict(self)

    @staticmethod
    def from_dict(d: dict) -> "ReviewCard":
        return ReviewCard(**d)


@dataclass
class CardSet:
    """一个来源的卡片集合"""
    source: str                          # 来源名称
    source_type: str                     # 类型
    category: str = "未分类"
    cards: List[ReviewCard] = field(default_factory=list)

    def add_card(self, question: str, answer: str, hint: str = "",
                 tags: Optional[List[str]] = None) -> ReviewCard:
        card_id = hashlib.md5(f"{self.source}:{question}".encode()).hexdigest()[:12]
        card = ReviewCard(
            id=card_id,
            source=self.source,
            source_type=self.source_type,
            category=self.category,
            question=question,
            answer=answer,
            hint=hint,
            tags=tags or []
        )
        # 去重
        for existing in self.cards:
            if existing.id == card_id:
                return existing
        self.cards.append(card)
        return card


# ═══════════════════════════════════════════════════
# SM-2 间隔算法（简化版）
# ═══════════════════════════════════════════════════

class SpacedRepetition:
    """
    SM-2简化版: 根据掌握度调整间隔
    掌握度 0→1: 1天
    掌握度 1→2: 3天
    掌握度 2→3: 7天
    掌握度 3→4: 14天
    掌握度 4→5: 30天
    掌握度下降: 重置到上一步间隔
    """

    INTERVAL_MAP = {0: 1, 1: 3, 2: 7, 3: 14, 4: 30, 5: 90}

    @staticmethod
    def next_interval(current_mastery: int, new_mastery: int,
                      current_interval: int) -> int:
        """计算下次间隔"""
        if new_mastery <= current_mastery:
            # 退步 → 间隔减半（最低1天）
            return max(1, current_interval // 2)
        # 进步 → 按新掌握度查表
        mapped = SpacedRepetition.INTERVAL_MAP.get(min(new_mastery, 5), 30)
        return max(current_interval, mapped)  # 只增不减（除非退步）

    @staticmethod
    def update_card(card: ReviewCard, new_mastery: int) -> ReviewCard:
        """更新卡片状态"""
        card.interval_days = SpacedRepetition.next_interval(
            card.mastery, new_mastery, card.interval_days
        )
        card.mastery = min(new_mastery, 5)
        card.last_review = datetime.now().strftime("%Y-%m-%d")
        card.next_review = (datetime.now() + timedelta(days=card.interval_days)).strftime("%Y-%m-%d")
        card.review_count += 1
        return card


# ═══════════════════════════════════════════════════
# 卡片存储
# ═══════════════════════════════════════════════════

class CardStore:
    """管理所有卡片的持久化"""

    def __init__(self):
        self._index_path = REVIEW_DIR / "index.json"
        self._cards: Dict[str, ReviewCard] = {}
        self._load()

    def _load(self):
        if self._index_path.exists():
            try:
                data = json.loads(self._index_path.read_text(encoding="utf-8"))
                for d in data:
                    card = ReviewCard.from_dict(d)
                    self._cards[card.id] = card
            except:
                pass

    def save(self):
        """保存所有卡片到index.json"""
        data = [c.to_dict() for c in self._cards.values()]
        self._index_path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8"
        )

    def add_card(self, card: ReviewCard):
        if card.id not in self._cards:
            self._cards[card.id] = card

    def get_due_cards(self, check_date: Optional[str] = None) -> List[ReviewCard]:
        """获取到期需复习的卡片"""
        today = check_date or datetime.now().strftime("%Y-%m-%d")
        due = []
        for card in self._cards.values():
            if card.next_review and card.next_review <= today:
                due.append(card)
        # 按掌握度升序（先复习最不熟的）
        due.sort(key=lambda c: (c.mastery, c.next_review))
        return due

    def get_cards_by_source(self, source: str) -> List[ReviewCard]:
        return [c for c in self._cards.values() if c.source == source]

    def get_cards_by_category(self, category: str) -> List[ReviewCard]:
        return [c for c in self._cards.values() if c.category == category]

    def count(self) -> int:
        return len(self._cards)

    def stats(self) -> dict:
        """统计概览"""
        by_mastery = {}
        by_category = {}
        for c in self._cards.values():
            by_mastery[c.mastery] = by_mastery.get(c.mastery, 0) + 1
            by_category[c.category] = by_category.get(c.category, 0) + 1
        
        today = datetime.now().strftime("%Y-%m-%d")
        due = sum(1 for c in self._cards.values() 
                  if c.next_review and c.next_review <= today)
        
        return {
            "total": len(self._cards),
            "due_today": due,
            "by_mastery": dict(sorted(by_mastery.items())),
            "by_category": dict(sorted(by_category.items(), key=lambda x: -x[1])),
        }


# ═══════════════════════════════════════════════════
# 知识点抽取器
# ═══════════════════════════════════════════════════

class KnowledgeExtractor:
    """
    从文件/目录中提取知识点
    支持: .md .py .txt (代码级解析)
    大型.pptx/.pdf: 通过文件名+目录名推断主题
    强化抽取: 针对"技能包=教你怎么用的文档"做内容感知
    """

    # ========== 场景知识库（硬编码高价值卡片） ==========
    _SCENE_CARDS: Dict[str, List[tuple]] = {
        "复杂问题分析": [
            ("复杂问题分析的四个模块是什么？",
             "第一性原理(拆到底层)、5Why根因分析(追问到底)、约束分层(真限制vs假限制)、杠杆点识别(找最该先动的点)",
             "每个模块都配有5份内容：先看说明→直接复制用→结果示例→使用步骤→进阶"),
            ("第一性原理的核心用法是什么？",
             "把问题拆到底层变量，不靠类比和过去的经验，而是回到物理/数学/逻辑的基本事实去重新推导",
             "适合『事情看起来都很熟悉但解决不了』的时候"),
            ("杠杆点识别的判断标准是什么？",
             "从一堆问题里找『动了之后其他问题也自然松动』的那个点，不是最紧急的，而是最有杠杆效应的",
             "参考：二八法则 + 因果链分析"),
            ("约束分层怎么区分真限制和假限制？",
             "真限制=物理/法律/资源硬上限，假限制=『以为不行』的内心限制。把假限制转化为『怎么绕过』的问题",
             "常见陷阱：把习惯当限制，把恐惧当限制"),
        ],
        "黑天鹅": [
            ("黑天鹅事件的三个特征是什么？",
             "1)稀有性——超出常规预期 2)极端冲击——影响巨大 3)事后可预测性——人们总能在事后找到解释",
             "塔勒布《黑天鹅》核心"),
            ("应对不确定性的12个框架中，杠铃策略是什么？",
             "放弃『中庸』，同时持有极端保守+极端激进。大部分资产放在安全区，小部分赌高赔率机会",
             "适合个人职业和投资组合"),
            ("什么叫『反脆弱』？和韧性有什么区别？",
             "韧性是『扛住冲击不变形』，反脆弱是『在冲击中变得更强』。每次失败/波动都是系统进化的信号",
             "塔勒布三部曲：随机漫步→黑天鹅→反脆弱"),
        ],
        "原子习惯": [
            ("习惯养成的四步法则是什么？",
             "1)提示——让它显而易见 2)渴求——让它有吸引力 3)反应——让它简便易行 4)奖励——让它令人愉悦",
             "James Clear《原子习惯》"),
            ("如何用『两分钟规则』养成新习惯？",
             "新习惯的开始版本不超过2分钟。想读书→读一页，想健身→穿上运动鞋。降低启动门槛到『不可能拒绝』",
             "关键不是做多少，而是先建立『做』的身份认同"),
            ("什么叫『习惯叠加』？",
             "把已有习惯作为触发器绑定新习惯：『在[已有习惯]之后，我会[新习惯]』",
             "例如：喝完咖啡后，立刻做5个俯卧撑"),
        ],
        "鬼谷子": [
            ("鬼谷子沟通谈判的核心策略是什么？",
             "『捭阖』——捭者开也，阖者闭也。该说话时说话(打开)，该沉默时沉默(关闭)。节奏控制比内容更重要",
             "纵横家鼻祖"),
            ("『反应术』在谈判中怎么用？",
             "先听对方说，从对方的反应中获取信息。『欲闻其声反默，欲张反敛，欲高反下』——想听对方说，你先沉默",
             "以退为进的博弈智慧"),
        ],
        "阳明心学": [
            ("『知行合一』到底是什么意思？",
             "知和行不是两件事——知而不行只是『未知』。真正『知道』一件事，就是已经在做的状态",
             "王阳明核心思想"),
            ("『致良知』的实践方法是什么？",
             "每个人都有判断是非的『良知』，不需要外求。做事前先静下来问自己『这件事真的对么』，内心的答案就是准则",
             "与康德『道德律令』有异曲同工"),
        ],
        "系统之美": [
            ("系统的三个基本构成是什么？",
             "要素(人/物/钱)、连接(关系/流程/反馈)、功能(系统的目的)。改变要素不影响系统，改变连接才改变系统",
             "Donella Meadows《系统之美》"),
            ("什么是『反馈回路』？",
             "增强回路(雪球效应，越滚越大) vs 平衡回路(调节效应，维持稳定)。几乎所有系统问题都是反馈回路失调",
             "识别回路 = 找到系统杠杆点"),
        ],
        "电商": [
            ("跨境电商选品的六条标准是什么？",
             "1)高毛利>30% 2)轻小件(运费低) 3)不易碎 4)无品牌壁垒 5)有差异化空间 6)搜索量上升趋势",
             "skill_ecom_ops"),
            ("私域运营的SOP核心三要素是什么？",
             "1)用户分层(新客/活跃/沉睡) 2)内容节奏(不刷屏但不断联) 3)转化设计(低客单暖场→高客单收割)",
             "来自电商运营5包汇总"),
        ],
        "量化交易": [
            ("量化交易中『未来函数』是什么意思？",
             "在回测中使用未来才会知道的数据做决策（如用明天的收盘价决定今天买入），导致回测漂亮实盘惨淡",
             "特征工程防坑第一原则"),
            ("Walk-Forward验证的四级判定是什么？",
             "P0=样本内过拟合 P1=样本外持平 P2=样本外稳定 P3=多时段一致 P4=实盘可盈利",
             "skill_quant_walk_forward_validation"),
            ("特征工程中如何防止数据泄露？",
             "1)所有特征只能用t时刻及之前的数据 2)rolling计算用expanding窗口 3)分组归一化在训练集内完成 4)时间序列切分不能随机打乱",
             "skill_quant_feature_engineering"),
        ],
        "AI Agent": [
            ("Agent的感知-思考-行动循环是什么？",
             "Observe(感知环境/输入)→Think(推理/规划/决策)→Act(执行动作/工具调用)，循环直到任务完成",
             "GA核心架构"),
            ("MCP协议的核心价值是什么？",
             "标准化的工具/资源/提示暴露方式，让任意Agent能即插即用任意MCP Server，打破『每个Agent绑死一套工具』的孤岛",
             "skill_mcp_complete"),
            ("LangGraph的StateGraph有什么用？",
             "有状态的图式Agent编排：节点=处理逻辑，边=条件路由，状态在节点间传递。适合复杂多步工作流",
             "skill_langgraph"),
        ],
    }

    @staticmethod
    def _match_scene(path_str: str) -> Optional[str]:
        """匹配文件路径到场景名称"""
        pl = path_str.lower().replace("\\", "/")
        for key in KnowledgeExtractor._SCENE_CARDS:
            if key.lower() in pl:
                return key
        return None

    @staticmethod
    def extract_from_md(filepath: Path) -> List[Tuple[str, str, str]]:
        """从markdown提取知识点 → 强化版"""
        # 第一步: 尝试场景匹配（高精度卡片）
        scene_key = KnowledgeExtractor._match_scene(str(filepath))
        if scene_key:
            return KnowledgeExtractor._SCENE_CARDS[scene_key]

        cards = []
        try:
            text = filepath.read_text(encoding="utf-8", errors="replace")
        except:
            return cards

        lines = text.split("\n")
        title = filepath.stem.replace("_", " ").replace("-", " ")
        
        # 找标题
        headers = []
        for line in lines:
            line = line.strip()
            if line.startswith("# ") or line.startswith("## ") or line.startswith("### "):
                headers.append(line.lstrip("# ").strip())
        
        main_title = headers[0] if headers else title

        # 策略A: 提取 ## 标题 + 下面第一段内容 → Q&A
        current_header = ""
        for line in lines:
            stripped = line.strip()
            if stripped.startswith("## ") or stripped.startswith("### "):
                current_header = stripped.lstrip("# ").strip()
            elif current_header and stripped and len(stripped) > 20 and not stripped.startswith("#"):
                if "。" in stripped[5:80]:
                    idx = stripped.index("。", 5)
                    q_part = stripped[:idx].strip()
                    a_part = stripped[idx+1:idx+120].strip()
                    if len(q_part) > 6 and len(a_part) > 6:
                        cards.append((f"《{main_title}》中『{current_header}』的核心内容？",
                                      f"{q_part}。{a_part}" if a_part else q_part + "。",
                                      f"来自《{main_title}》"))
                        current_header = ""  # 用完重置
                        if len(cards) >= 6:
                            break

        # 策略B: 提取-列表项（如果策略A不够）
        if len(cards) < 3:
            items = []
            for line in lines:
                line = line.strip()
                if line.startswith("- ") or line.startswith("* "):
                    content = line[2:].strip()
                    if len(content) > 10 and "：" in content[:40]:
                        parts = content.split("：", 1)
                        items.append((parts[0].strip()[:30], parts[1].strip()))
            
            for q, a in items[:6]:
                if len(q) < 3 or len(a) < 3:
                    continue
                cards.append((f"《{main_title}》中『{q}』是什么意思？",
                              a, f"来自《{main_title}》"))
        
        # 策略C: 空卡片时生成通用引导卡
        if len(cards) == 0:
            # 从文件内容摘要
            clean_lines = [l.strip() for l in lines if l.strip() and not l.startswith("#")
                          and not l.startswith("```") and not l.startswith("[")]
            summary = " ".join(clean_lines[:10])[:150]
            if summary:
                cards.append((f"《{main_title}》的主要内容是什么？",
                              summary + ("..." if len(summary) >= 150 else ""),
                              "技能包知识卡片"))
        
        return cards[:8]

    @staticmethod
    def extract_from_py(filepath: Path) -> List[Tuple[str, str, str]]:
        """从Python文件提取知识点（类/函数/文档字符串）"""
        cards = []
        try:
            text = filepath.read_text(encoding="utf-8", errors="replace")
        except:
            return cards
        
        lines = text.split("\n")
        filename = filepath.stem
        
        in_class = ""
        in_func = ""
        doc_lines = []
        
        for line in lines:
            stripped = line.strip()
            
            # 收集docstring
            if stripped.startswith('"""') or stripped.startswith("'''"):
                if doc_lines:
                    # 结束
                    doc_text = " ".join(doc_lines)
                    if in_class:
                        q = f"{in_class}类的作用是？"
                        cards.append((q, doc_text[:80], f"类: {in_class}"))
                    elif in_func:
                        q = f"{in_func}()函数的作用是？"
                        cards.append((q, doc_text[:80], f"函数: {in_func}"))
                    doc_lines = []
                else:
                    # 开始
                    doc_text = stripped[3:].strip()
                    if doc_text:
                        doc_lines = [doc_text]
                    continue
            
            if doc_lines:
                doc_lines.append(stripped)
            
            if stripped.startswith("class "):
                in_class = stripped.split("(")[0].replace("class ", "").strip().rstrip(":")
                in_func = ""
            elif stripped.startswith("def "):
                in_func = stripped.split("(")[0].replace("def ", "").strip().rstrip(":")
        
        return cards[:8]

    @staticmethod
    def extract_from_pptx_name(filename: str) -> List[Tuple[str, str, str]]:
        """从PPT文件名提取主题卡片"""
        name = filename.replace(".pptx", "").replace("+", " ").replace("_", " ").strip()
        
        # 去掉开头的数字/符号
        while name and (name[0].isdigit() or name[0] in "_+ "):
            name = name[1:].strip()
        
        # 推断类别
        categories = {
            "思维": "思维模型", "模型": "思维模型", "框架": "思维模型",
            "指南": "实操指南", "教程": "实操指南", "入门": "实操指南",
            "量化": "量化交易", "数据": "数据分析",
            "工程": "技术工程", "开发": "技术工程",
            "电商": "电商运营", "运营": "电商运营",
            "职场": "职场技能", "求职": "职场技能",
            "理财": "理财", "投资": "理财", "金钱": "理财",
            "习惯": "习惯养成", "原子": "习惯养成",
        }
        category = "知识体系"
        for kw, cat in categories.items():
            if kw in name:
                category = cat
                break
        
        cards = [
            (f"《{name}》的核心主题是什么？",
             f"这是一份关于{name}的完整知识体系文档，涵盖核心概念、实用方法和案例分析。",
             f"来自思维技能包"),
            (f"《{name}》可以应用在什么场景？",
             f"适用于需要{category}相关知识和技能的场景，帮助系统化理解和应用。",
             f"类别: {category}"),
        ]
        
        return cards


# ═══════════════════════════════════════════════════
# 主控制器: ReviewMaster
# ═══════════════════════════════════════════════════

class ReviewMaster:
    """
    复习主控制器
    自动管理所有技能包/文档的复习卡片
    """

    def __init__(self):
        self.store = CardStore()
        self.extractor = KnowledgeExtractor()
        self._log: List[str] = []

    def log(self, msg: str):
        self._log.append(msg)
        print(f"  📝 {msg}")

    def scan_all(self) -> Dict[str, Any]:
        """
        全面扫描，为所有技能包和文档生成复习卡片
        返回统计结果
        """
        start = time.time()
        new_cards = 0
        
        # 1. 扫描技能包目录 (.md, .py, .txt)
        if SKILL_DIR.exists():
            for dirpath, dirs, files in os.walk(SKILL_DIR):
                # 忽略MACOS系统文件
                if "__MACOSX" in dirpath or ".DS_Store" in str(dirpath):
                    continue
                
                # 确定来源名称
                rel = Path(dirpath).relative_to(SKILL_DIR)
                source_name = str(rel)
                
                for f in files:
                    fp = Path(dirpath) / f
                    ext = f.lower()
                    
                    # 太小的文件跳过
                    if fp.stat().st_size < 100:
                        continue
                    
                    # --- .md文件 ---
                    if ext.endswith(".md") and not f.startswith("."):
                        cards_data = self.extractor.extract_from_md(fp)
                        if cards_data:
                            cs = CardSet(source=str(rel), source_type="skill", 
                                        category=self._guess_category(str(rel)))
                            for q, a, hint in cards_data:
                                card = cs.add_card(q, a, hint)
                                self.store.add_card(card)
                                new_cards += 1
                    
                    # --- .py文件 ---
                    elif ext.endswith(".py") and not f.startswith("."):
                        cards_data = self.extractor.extract_from_py(fp)
                        if cards_data:
                            cs = CardSet(source=str(rel), source_type="code",
                                        category=self._guess_category(str(rel)))
                            for q, a, hint in cards_data:
                                card = cs.add_card(q, a, hint)
                                self.store.add_card(card)
                                new_cards += 1
        
        # 2. 扫描大文档(.pptx, .pdf)
        if SKILL_DIR.exists():
            for f in SKILL_DIR.glob("*.pptx"):
                if f.stat().st_size < 50000:
                    continue
                cards_data = self.extractor.extract_from_pptx_name(f.name)
                if cards_data:
                    category = self._guess_category(f.stem)
                    cs = CardSet(source=f.name, source_type="ppt", category=category)
                    for q, a, hint in cards_data:
                        card = cs.add_card(q, a, hint)
                        self.store.add_card(card)
                        new_cards += 1
        
        # 3. 保存
        self.store.save()
        elapsed = time.time() - start
        
        stats = self.store.stats()
        stats["new_cards_added"] = new_cards
        stats["elapsed_seconds"] = round(elapsed, 2)
        
        self.log(f"扫描完成: 新增{new_cards}张卡片, 总计{stats['total']}张")
        self.log(f"今日待复习: {stats['due_today']}张")
        self.log(f"类别分布: {dict(sorted(stats['by_category'].items(), key=lambda x: -x[1]))}")
        
        return stats

    def daily_review(self, count: int = 5) -> List[Dict[str, Any]]:
        """
        每日复习 → 返回今天到期的卡片列表
        count: 一次最多返回几张
        """
        due = self.store.get_due_cards()
        if not due:
            self.log("今日无待复习卡片 🎉")
            return []
        
        selected = due[:count]
        results = []
        
        self.log(f"今日待复习{len(due)}张, 本次抽取{len(selected)}张:")
        for card in selected:
            results.append({
                "id": card.id,
                "source": card.source,
                "category": card.category,
                "question": card.question,
                "answer": card.answer,
                "hint": card.hint,
                "mastery": card.mastery,
                "interval": card.interval_days,
            })
            self.log(f"  [{card.category}] {card.question[:40]}... (掌握度{card.mastery})")
        
        return results

    def submit_review(self, card_id: str, new_mastery: int) -> bool:
        """
        提交复习结果
        card_id: 卡片ID
        new_mastery: 0-5 新掌握度
        """
        if card_id not in self.store._cards:
            return False
        
        card = self.store._cards[card_id]
        old_mastery = card.mastery
        SpacedRepetition.update_card(card, new_mastery)
        self.store.save()
        
        direction = "↑进步" if new_mastery > old_mastery else ("↓退步" if new_mastery < old_mastery else "→持平")
        self.log(f"卡片'{card.question[:30]}...' {direction}: 掌握度{old_mastery}→{new_mastery}, "
                f"下次{card.interval_days}天后({card.next_review})")
        
        return True

    def review_by_category(self, category: str) -> List[Dict[str, Any]]:
        """按类别复习"""
        cards = self.store.get_cards_by_category(category)
        if not cards:
            self.log(f"类别'{category}'无卡片")
            return []
        
        # 先复习最不熟的
        cards.sort(key=lambda c: (c.mastery, c.next_review))
        
        results = []
        for card in cards[:5]:
            results.append({
                "id": card.id,
                "question": card.question,
                "answer": card.answer,
                "hint": card.hint,
                "mastery": card.mastery,
            })
        
        self.log(f"类别'{category}'共{len(cards)}张, 取{len(results)}张复习")
        return results

    def stats(self) -> dict:
        """整体统计"""
        return self.store.stats()

    @staticmethod
    def _guess_category(path_str: str) -> str:
        """根据路径猜类别"""
        pl = path_str.lower()
        if "思维" in pl or "模型" in pl:
            return "思维模型"
        if "量化" in pl:
            return "量化交易"
        if "数据" in pl:
            return "数据分析"
        if "电商" in pl:
            return "电商运营"
        if "工程" in pl or "开发" in pl or "llm" in pl or "ai" in pl:
            return "技术工程"
        if "运营" in pl or "内容" in pl or "新媒体" in pl:
            return "内容运营"
        if "产品" in pl:
            return "产品经理"
        if "管理" in pl or "项目" in pl:
            return "项目管理"
        if "前端" in pl or "后端" in pl or "全栈" in pl:
            return "技术工程"
        if "习惯" in pl or "深度" in pl:
            return "个人成长"
        if "求职" in pl or "职场" in pl or "hr" in pl:
            return "职场技能"
        if "理财" in pl or "金钱" in pl:
            return "理财"
        if "道德" in pl or "孙子" in pl or "阳明" in pl or "哲学" in pl:
            return "哲学智慧"
        if "龙虾" in pl or "agent" in pl:
            return "AI Agent"
        return "综合知识"


# ═══════════════════════════════════════════════════
# CLI入口 & 测试
# ═══════════════════════════════════════════════════

def cli():
    """命令行入口"""
    import argparse
    parser = argparse.ArgumentParser(description="GA间隔复习系统")
    parser.add_argument("--scan", action="store_true", help="全面扫描生成卡片")
    parser.add_argument("--review", action="store_true", help="每日复习")
    parser.add_argument("--stats", action="store_true", help="查看统计")
    parser.add_argument("--category", type=str, help="按类别复习")
    parser.add_argument("--count", type=int, default=5, help="复习数量")
    args = parser.parse_args()
    
    master = ReviewMaster()
    
    if args.scan:
        print("🔍 开始全面扫描...")
        stats = master.scan_all()
        print(f"\n  总计: {stats['total']}张卡片, 新增: {stats['new_cards_added']}张")
        print(f"  耗时: {stats['elapsed_seconds']}秒")
    
    elif args.review:
        print(f"📖 今日复习 (取{args.count}张)...")
        cards = master.daily_review(args.count)
        print(f"\n  共{len(cards)}张卡片待复习")
    
    elif args.category:
        print(f"📖 类别复习: {args.category}")
        cards = master.review_by_category(args.category)
        if cards:
            for c in cards:
                print(f"\n  Q: {c['question']}")
                print(f"  A: {c['answer']}")
                print(f"  掌握度: {c['mastery']}")
    
    elif args.stats:
        stats = master.stats()
        print(f"\n📊 复习系统统计")
        print(f"  总卡片: {stats['total']}")
        print(f"  今日待复习: {stats['due_today']}")
        print(f"  按掌握度: {stats['by_mastery']}")
        print(f"  按类别:")
        for cat, cnt in stats.get('by_category', {}).items():
            print(f"    {cat}: {cnt}张")
    
    else:
        parser.print_help()


if __name__ == "__main__":
    cli()
