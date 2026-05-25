"""
===========================================================
 skill_photo_analyzer.py v2.0
 照片视觉分析引擎（深度学习+CV融合版）
 Photo Visual Analysis Engine (Deep Learning + CV Fusion)
===========================================================

【功能】
 融合三股力量"看懂"装修照片：
 1️⃣ 深度学习（PyTorch + MobileNet V3 + EfficientNet B0）→ 认物体
 2️⃣ 传统CV（OpenCV Canny/Hough/Laplacian）→ 看结构
 3️⃣ 装修知识词库 → 懂装修

【用法】
 from skills.skill_photo_analyzer import analyze_decoration_photos
 results = analyze_decoration_photos("E:/GenericAgent_Workspace/内容库/工地图")

【依赖】
 torch, torchvision, opencv-python, pillow, numpy
===========================================================
"""

import os
import cv2
import numpy as np
from PIL import Image
import torch
import torchvision
from torchvision import transforms
from typing import List, Dict, Optional, Tuple
import requests
import warnings
warnings.filterwarnings('ignore')

# ===========================================================
# 一、深度学习模型管理
# ===========================================================
class DeepVisionModel:
    """管理双模型深度学习视觉分析"""
    
    # 装修相关ImageNet类别映射
    FURNITURE_MAP = {
        'wardrobe': ['衣柜', '定制柜', '柜体', 'cabinet', 0.7],
        'sliding_door': ['移门', '推拉门', '柜门', 'sliding door', 0.6],
        'medicine_chest': ['药柜', '小柜子', '格子柜', 'medicine chest', 0.5],
        'file': ['文件柜', '文件夹', '档案柜', 'file cabinet', 0.5],
        'desk': ['书桌', '桌子', '台面', 'desk', 0.5],
        'chest': ['柜子', '箱子', '储物柜', 'chest', 0.5],
        'bookshelf': ['书架', '置物架', '书架', 'bookshelf', 0.6],
        'refrigerator': ['冰箱', '家电', '家电', 'refrigerator', 0.4],
        'dishwasher': ['洗碗机', '家电', '嵌入式', 'dishwasher', 0.4],
        'washer': ['洗衣机', '家电', 'washer', 0.4],
        'window_shade': ['百叶窗', '窗帘', '遮阳', 'window shade', 0.4],
        'screen': ['屏风', '隔断', 'screen', 0.4],
        'switch': ['开关', '插座', 'switch', 0.3],
        'lamp': ['灯具', '灯', 'lamp', 0.3],
        'screwdriver': ['螺丝刀', '工具', '五金', 'screwdriver', 0.3],
        'envelope': ['信封', '纸', 'envelope', 0.2],
        'binder': ['文件夹', ' binder', 'binder', 0.3],
        'tub': ['浴缸', 'tub', 0.3],
        'washbasin': ['洗手盆', '台盆', 'washbasin', 0.3],
        'bathtub': ['浴缸', 'bathtub', 0.3],
    }
    
    def __init__(self):
        self.models_loaded = False
        self.model_large = None
        self.model_eff = None
        self.preprocess = None
        self.labels = None
        self.furniture_indices = set()
        
    def load_models(self) -> bool:
        """加载预训练模型（MobileNet V3 + EfficientNet B0）"""
        if self.models_loaded:
            return True
            
        try:
            print("⏳ 加载深度学习视觉模型...")
            
            # MobileNet V3 Large (21MB)
            weights_large = torchvision.models.MobileNet_V3_Large_Weights.IMAGENET1K_V2
            self.model_large = torchvision.models.mobilenet_v3_large(weights=weights_large)
            self.model_large.eval()
            self.preprocess = weights_large.transforms()
            
            # EfficientNet B0 (20.5MB)
            weights_eff = torchvision.models.EfficientNet_B0_Weights.IMAGENET1K_V1
            self.model_eff = torchvision.models.efficientnet_b0(weights=weights_eff)
            self.model_eff.eval()
            
            # 下载ImageNet标签
            try:
                r = requests.get(
                    "https://raw.githubusercontent.com/pytorch/hub/master/imagenet_classes.txt",
                    timeout=10
                )
                self.labels = [line.strip() for line in r.text.strip().split('\n')]
            except:
                self.labels = [f"class_{i}" for i in range(1000)]
            
            # 提取装修相关类别
            furniture_keywords = ['wardrobe', 'cabinet', 'chest', 'desk', 'shelf', 
                                 'door', 'drawer', 'file', 'furniture', 'table',
                                 'counter', 'cupboard', 'locker', 'rack', 'box']
            for i, label in enumerate(self.labels):
                label_lower = label.lower().replace(' ', '_')
                if any(kw in label_lower for kw in furniture_keywords):
                    self.furniture_indices.add(i)
            
            self.models_loaded = True
            print(f"✅ 视觉模型就绪！分类数: {len(self.labels)}, 装修相关: {len(self.furniture_indices)}")
            return True
            
        except Exception as e:
            print(f"⚠️ 深度学习模型加载失败: {e}")
            # 降级运行：仅用OpenCV
            return False
    
    def classify_image(self, img: Image.Image) -> Dict:
        """对图片做双模型投票分类"""
        if not self.models_loaded:
            return {"error": "模型未加载"}
        
        input_tensor = self.preprocess(img).unsqueeze(0)
        
        with torch.no_grad():
            out_large = self.model_large(input_tensor)
            out_eff = self.model_eff(input_tensor)
        
        # 双模型平均投票
        probs_large = torch.nn.functional.softmax(out_large[0], dim=0)
        probs_eff = torch.nn.functional.softmax(out_eff[0], dim=0)
        combined = (probs_large + probs_eff) / 2
        
        # 全类别Top5
        top5_all = torch.topk(combined, 5)
        
        # 家具类别Top5
        furniture_probs = [(i, combined[i].item()) for i in self.furniture_indices]
        furniture_probs.sort(key=lambda x: x[1], reverse=True)
        top5_furniture = furniture_probs[:5]
        
        result = {
            "top5_all": [
                {
                    "label_en": self.labels[idx.item()],
                    "score": round(score.item() * 100, 1)
                }
                for idx, score in zip(top5_all.indices, top5_all.values)
            ],
            "top5_furniture": [
                {
                    "label_en": self.labels[idx],
                    "label_cn": self._to_chinese(self.labels[idx]),
                    "score": round(score * 100, 1)
                }
                for idx, score in top5_furniture
            ],
            "top_furniture_score": round(top5_furniture[0][1] * 100, 1) if top5_furniture else 0,
            "has_furniture": top5_furniture[0][1] > 0.15 if top5_furniture else False
        }
        
        # 推断主要物体
        furniture_scores = {}
        for idx, score in top5_furniture:
            label = self.labels[idx]
            cn_names = self._to_chinese_list(label)
            for cn in cn_names:
                furniture_scores[cn] = furniture_scores.get(cn, 0) + score
        
        result["main_objects"] = sorted(
            furniture_scores.items(), key=lambda x: x[1], reverse=True
        )[:5]
        
        return result
    
    def _to_chinese(self, label_en: str) -> str:
        """英文标签→中文装修术语"""
        key = label_en.lower().replace(' ', '_')
        for k, v in self.FURNITURE_MAP.items():
            if k in key or key in k:
                return v[0]
        return label_en
    
    def _to_chinese_list(self, label_en: str) -> List[str]:
        """获取一个标签所有可能的中文解释"""
        key = label_en.lower().replace(' ', '_')
        for k, v in self.FURNITURE_MAP.items():
            if k in key or key in k:
                # v = [cn_name1, cn_name2, ..., cn_nameN, threshold]
                return [x for x in v if isinstance(x, str)]
        return [label_en]
    
    def analyze_regions(self, img: Image.Image, grid: int = 3) -> List[Dict]:
        """九宫格区域分析"""
        if not self.models_loaded:
            return []
        
        w, h = img.size
        regions = []
        for gy in range(grid):
            for gx in range(grid):
                rw, rh = w // grid, h // grid
                rx, ry = gx * rw, gy * rh
                region_img = img.crop((rx, ry, rx + rw, ry + rh))
                region_result = self.classify_image(region_img)
                
                # 汇总最佳发现
                objects = region_result.get("main_objects", [])
                regions.append({
                    "position": (gx, gy),
                    "objects": objects,
                    "has_furniture": region_result.get("has_furniture", False)
                })
        
        return regions


# ===========================================================
# 二、CV结构分析（原有升级版）
# ===========================================================
class CVStructureAnalyzer:
    """OpenCV结构分析"""
    
    def analyze(self, img_cv: np.ndarray) -> Dict:
        """分析图片结构特征"""
        h, w = img_cv.shape[:2]
        gray = cv2.cvtColor(img_cv, cv2.COLOR_BGR2GRAY)
        
        # 边缘密度
        edges = cv2.Canny(gray, 50, 150)
        edge_density = float(np.count_nonzero(edges) / (h * w) * 10000)
        
        # 线条检测（柜体结构）
        lines = cv2.HoughLinesP(edges, 1, np.pi/180, 50, minLineLength=50, maxLineGap=10)
        h_lines, v_lines = 0, 0
        if lines is not None:
            for line in lines:
                x1, y1, x2, y2 = line[0]
                angle = abs(np.arctan2(y2 - y1, x2 - x1) * 180 / np.pi)
                if angle < 25:
                    h_lines += 1
                elif angle > 65:
                    v_lines += 1
        
        # 锐度
        sharpness = float(cv2.Laplacian(gray, cv2.CV_64F).var())
        
        # 亮度
        mean_bright = float(np.mean(gray))
        dark_pct = float(np.count_nonzero(gray < 50) / (h * w) * 100)
        bright_pct = float(np.count_nonzero(gray > 200) / (h * w) * 100)
        
        # 柜门缝隙检测
        center = gray[h//3:2*h//3, :]
        vert_proj = np.min(center, axis=0)
        dark_stripes = vert_proj < np.mean(vert_proj) * 0.75
        gap_count = 0
        prev = False
        for v in dark_stripes:
            if v and not prev:
                gap_count += 1
                prev = True
            elif not v:
                prev = False
        
        # 颜色
        hsv = cv2.cvtColor(img_cv, cv2.COLOR_BGR2HSV)
        mean_hue = float(np.mean(hsv[:,:,0]))
        
        # 材质/颜色倾向
        if mean_hue < 30 or mean_hue > 150:
            color_tone = "暖色（木色/暖白）"
        elif 80 < mean_hue < 130:
            color_tone = "冷色（白色/冷灰）"
        else:
            color_tone = "中性色"
        
        return {
            "edge_density": round(edge_density, 1),
            "h_lines": h_lines,
            "v_lines": v_lines,
            "sharpness": round(sharpness, 1),
            "brightness": round(mean_bright, 1),
            "dark_pct": round(dark_pct, 1),
            "bright_pct": round(bright_pct, 1),
            "gaps": gap_count,
            "color_tone": color_tone,
            "is_sharp": sharpness > 100,
            "is_well_lit": bright_pct > 15,
            "is_cabinet": h_lines > 100 and v_lines > 50,
            "is_multiple_doors": gap_count >= 5,
            "is_full_wall": h_lines > 1000 and v_lines > 500,
        }


# ===========================================================
# 三、装修知识引擎
# ===========================================================
class DecorationKnowledge:
    """装修知识：将视觉分析结果翻译成装修术语"""
    
    # 场景类型字典
    SCENE_MAP = [
        (lambda dl, cv: cv["is_full_wall"], "全墙柜体展示", "满墙的定制柜体，柜门整齐排列"),
        (lambda dl, cv: cv["is_cabinet"] and cv["is_multiple_doors"], "柜门正面展示", "定制柜柜门正面对比，缝隙均匀"),
        (lambda dl, cv: cv["is_cabinet"], "柜体结构", "柜体框架和内部结构"),
        (lambda dl, cv: any("衣柜" in str(o) for o in dl.get("main_objects", [])), "衣柜区域", "衣柜/衣帽间区域"),
        (lambda dl, cv: any("柜子" in str(o) for o in dl.get("main_objects", [])), "柜体区域", "柜体/储物柜区域"),
        (lambda dl, cv: any("移门" in str(o) for o in dl.get("main_objects", [])), "移门展示", "推拉门/移门展示"),
        (lambda dl, cv: any("电器" in str(o) or "冰箱" in str(o) for o in dl.get("main_objects", [])), "电器嵌入", "嵌入式电器安装展示"),
        (lambda dl, cv: cv["sharpness"] > 120 and cv["h_lines"] < 50, "细节特写", "柜体细节/五金特写"),
        (lambda dl, cv: True, "空间整体", "整体空间展示"),
    ]
    
    @staticmethod
    def determine_scene(dl_result: Dict, cv_result: Dict) -> Tuple[str, str]:
        """根据深度学习和CV结果判断场景"""
        for condition, scene, desc in DecorationKnowledge.SCENE_MAP:
            if condition(dl_result, cv_result):
                return scene, desc
        return "空间整体", "整体空间展示"
    
    @staticmethod
    def generate_tags(dl_result: Dict, cv_result: Dict) -> List[str]:
        """生成装修标签"""
        tags = []
        
        # 从深度学习结果
        for obj_name, score in dl_result.get("main_objects", [])[:3]:
            if score > 0.15:
                tag = obj_name[:6]  # 缩短
                if tag not in tags:
                    tags.append(tag)
        
        # 从CV结果
        if cv_result["is_full_wall"]:
            tags.append("满墙柜")
        elif cv_result["is_cabinet"]:
            tags.append("柜体")
        if cv_result["is_multiple_doors"]:
            tags.append("多门板")
        if cv_result["is_well_lit"]:
            tags.append("光照充足")
        if cv_result["is_sharp"]:
            tags.append("清晰")
        if cv_result["dark_pct"] > 15:
            tags.append("暗部")
        if cv_result["gaps"] > 20:
            tags.append("多缝隙")
        
        # 去重、限制数量
        seen = set()
        unique_tags = []
        for t in tags:
            if t not in seen:
                seen.add(t)
                unique_tags.append(t)
        
        return unique_tags[:6]

    @staticmethod
    def suggest_content(scene: str, dl_result: Dict) -> Tuple[str, str, str]:
        """根据场景推荐内容和文案角度"""
        content_type_map = {
            "全墙柜体展示": ("全屋定制", "分享", "我家全屋定制做完啦，满墙柜体太能装了！"),
            "柜门正面展示": ("柜门", "避坑", "定制柜门缝隙不均匀？教你一眼看出问题！"),
            "柜体结构": ("定制柜", "教程", "定制柜内部结构怎么设计最实用？"),
            "衣柜区域": ("衣柜", "分享", "我的衣柜这样设计，收纳翻倍！"),
            "柜体区域": ("储物", "分享", "储物柜这样设计，空间利用率翻倍"),
            "移门展示": ("移门", "分享", "推拉门选对不选贵，这些细节要注意"),
            "电器嵌入": ("家电", "教程", "嵌入式电器安装攻略，收藏不亏"),
            "细节特写": ("五金", "避坑", "定制柜五金选不对，柜子一年就坏"),
            "空间整体": ("装修", "分享", "装修进度打卡｜今天工地长这样"),
        }
        
        default = ("装修", "分享", "装修日常打卡")
        return content_type_map.get(scene, default)


# ===========================================================
# 四、主分析函数
# ===========================================================
# 全局视觉模型（懒加载）
_vision_model = None

def get_vision_model() -> DeepVisionModel:
    """获取或初始化视觉模型（单例）"""
    global _vision_model
    if _vision_model is None:
        _vision_model = DeepVisionModel()
        _vision_model.load_models()
    return _vision_model


def analyze_single_photo(path: str) -> Optional[Dict]:
    """
    分析单张装修照片（深度学习+CV融合）
    
    返回结构化分析结果：
    - file: 文件名
    - size: (宽, 高)
    - scene_type: 场景类型
    - scene_desc: 场景描述
    - tags: 标签列表
    - content_type: 推荐内容类型
    - color_tone: 颜色倾向
    - objects: 识别到的物体
    - metrics: 结构指标
    - is_sharp: 是否清晰
    - is_well_lit: 是否光照充足
    - quality_score: 综合质量评分
    """
    if not os.path.isfile(path):
        return None
    
    try:
        pil_img = Image.open(path).convert('RGB')
    except Exception as e:
        print(f"❌ 无法打开图片: {e}")
        return None
    
    w, h = pil_img.size
    
    try:
        img_array = np.array(pil_img)
        img_cv = cv2.cvtColor(img_array[:, :, :3], cv2.COLOR_RGB2BGR)
    except:
        return None
    
    # === 第一阶段：深度学习分析 ===
    vision = get_vision_model()
    dl_result = vision.classify_image(pil_img)
    
    # === 第二阶段：CV结构分析 ===
    cv_analyzer = CVStructureAnalyzer()
    cv_result = cv_analyzer.analyze(img_cv)
    
    # === 第三阶段：装修知识融合 ===
    scene, scene_desc = DecorationKnowledge.determine_scene(dl_result, cv_result)
    tags = DecorationKnowledge.generate_tags(dl_result, cv_result)
    content_type, content_topic, content_suggestion = DecorationKnowledge.suggest_content(scene, dl_result)
    
    # === 综合评分 ===
    quality_score = 0
    if cv_result["is_sharp"]: quality_score += 25
    if cv_result["is_well_lit"]: quality_score += 20
    if cv_result["gaps"] > 10: quality_score += 15  # 有柜门缝隙说明有细节
    if cv_result["h_lines"] > 200: quality_score += 15  # 结构丰富
    if dl_result.get("has_furniture", False): quality_score += 15  # 认出是家具
    if dl_result.get("top_furniture_score", 0) > 30: quality_score += 10  # 置信度高
    
    return {
        "file": os.path.basename(path),
        "size": (w, h),
        "scene_type": scene,
        "scene_desc": scene_desc,
        "tags": tags,
        "content_type": content_type,
        "content_topic": content_topic,
        "content_suggestion": content_suggestion,
        "color_tone": cv_result["color_tone"],
        "objects": dl_result.get("main_objects", []),
        "metrics": {
            "edge_density": cv_result["edge_density"],
            "h_lines": cv_result["h_lines"],
            "v_lines": cv_result["v_lines"],
            "sharpness": cv_result["sharpness"],
            "brightness": cv_result["brightness"],
            "dark_pct": cv_result["dark_pct"],
            "bright_pct": cv_result["bright_pct"],
            "gaps": cv_result["gaps"],
            "color_tone": cv_result["color_tone"],
            "has_furniture": dl_result.get("has_furniture", False),
            "top_furniture_score": dl_result.get("top_furniture_score", 0),
        },
        "is_sharp": cv_result["is_sharp"],
        "is_well_lit": cv_result["is_well_lit"],
        "quality_score": quality_score,
    }


def analyze_decoration_photos(folder_path: str, max_photos: int = 20) -> List[Dict]:
    """
    批量分析装修照片文件夹
    
    参数:
        folder_path: 照片文件夹路径
        max_photos: 最大分析张数
        
    返回:
        按质量排序的照片分析结果列表（最佳照片在前）
    """
    if not os.path.isdir(folder_path):
        return []
    
    photos = [f for f in os.listdir(folder_path) 
              if f.lower().endswith(('.jpg', '.jpeg', '.png'))][:max_photos]
    
    results = []
    for i, photo in enumerate(photos):
        print(f"📷 正在分析 [{i+1}/{len(photos)}]: {photo[:35]}...", end=" ")
        path = os.path.join(folder_path, photo)
        result = analyze_single_photo(path)
        if result:
            results.append(result)
            print(f"✅ {result['scene_type']} ({result['quality_score']}分)")
        else:
            print("❌ 失败")
    
    # 按质量排序
    results.sort(key=lambda r: r["quality_score"], reverse=True)
    
    return results


def suggest_content_type(scene_type: str) -> str:
    """根据场景推荐文案类型"""
    mapping = {
        "全墙柜体展示": "避坑",
        "柜门正面展示": "避坑",
        "柜体结构": "教程",
        "衣柜区域": "收纳",
        "柜体区域": "收纳",
        "移门展示": "评测",
        "电器嵌入": "教程",
        "细节特写": "避坑",
        "空间整体": "日常",
    }
    return mapping.get(scene_type, "日常")


def suggest_tags_for_post(photo_info: Dict) -> List[str]:
    """生成小红书/抖音标签"""
    base_tags = ["装修", "装修日记", "全屋定制"]
    scene_tags = {
        "全墙柜体展示": ["定制柜", "满墙柜", "收纳"],
        "柜门正面展示": ["柜门", "柜体设计", "定制家具"],
        "柜体结构": ["柜体", "定制家具", "装修干货"],
        "衣柜区域": ["衣柜", "衣帽间", "收纳设计"],
        "柜体区域": ["储物柜", "收纳", "家居设计"],
        "移门展示": ["推拉门", "移门", "玻璃门"],
        "电器嵌入": ["嵌入式", "家电", "厨房设计"],
        "细节特写": ["五金", "细节", "装修避坑"],
        "空间整体": ["装修进度", "工地", "毛坯"],
    }
    
    tags = list(base_tags)
    scene = photo_info.get("scene_type", "")
    tags.extend(scene_tags.get(scene, ["装修日常"]))
    
    # 去重，限制数量
    seen = set()
    unique = []
    for t in tags:
        if t not in seen:
            seen.add(t)
            unique.append(t)
    
    return unique[:8]


# ===========================================================
# 五、自检
# ===========================================================
if __name__ == "__main__":
    print("=" * 60)
    print("skill_photo_analyzer.py v2.0 自检")
    print("=" * 60)
    
    checks = []
    
    # 1. 模块导入
    try:
        checks.append(("模块导入", True))
    except Exception as e:
        checks.append(("模块导入", False, str(e)))
    
    # 2. 核心类实例化
    try:
        cv = CVStructureAnalyzer()
        checks.append(("CVStructureAnalyzer", cv is not None))
    except Exception as e:
        checks.append(("CVStructureAnalyzer", False, str(e)))
    
    try:
        dk = DecorationKnowledge()
        checks.append(("DecorationKnowledge", dk is not None))
    except Exception as e:
        checks.append(("DecorationKnowledge", False, str(e)))
    
    # 3. 测试照片分析
    photo_dir = r"E:\GenericAgent_Workspace\内容库\工地图"
    if os.path.isdir(photo_dir):
        results = analyze_decoration_photos(photo_dir)
        checks.append(("照片分析", len(results) > 0))
        if results:
            print(f"\n📊 最佳照片: {results[0]['file']}")
            print(f"   场景: {results[0]['scene_type']}")
            print(f"   物体: {results[0]['objects']}")
            print(f"   标签: {results[0]['tags']}")
            print(f"   质量分: {results[0]['quality_score']}")
    
    # 打印结果
    print(f"\n{'='*60}")
    for check in checks:
        status = "✅" if check[1] else "❌"
        detail = f" - {check[2]}" if len(check) > 2 else ""
        print(f"  {status} {check[0]}{detail}")
    print(f"{'='*60}")
    
    all_pass = all(c[1] for c in checks)
    print(f"\n{'✅ 全部通过!' if all_pass else '❌ 有失败项!'}")
