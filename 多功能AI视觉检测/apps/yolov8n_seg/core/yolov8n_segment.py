from libs.PipeLine import PipeLine, ScopedTiming
from libs.AIBase import AIBase
from libs.AI2D import Ai2d
import os
import json
from media.media import *
from time import *
import nncase_runtime as nn
import ulab.numpy as np
import time
import utime
import image
import random
import gc
import sys
import aidemo

CFG_PATH = "/sdcard/configs/yolov8n_seg.json"

class ConfigManager:
    DEFAULTS = {
        "confidence_threshold": 0.2,
        "nms_threshold": 0.5,
        "mask_threshold": 0.5,
    }

    def __init__(self):
        self.conf = self._load()
        self._ensure_defaults()

    def _load(self):
        try:
            with open(CFG_PATH, "r") as f:
                return json.loads(f.read())
        except:
            return {}

    def _ensure_defaults(self):
        changed = False
        for k, v in self.DEFAULTS.items():
            if k not in self.conf:
                self.conf[k] = v
                changed = True
        if changed:
            self.save()

    def save(self):
        try:
            os.makedirs(os.path.dirname(CFG_PATH), exist_ok=True)
            with open(CFG_PATH, "w") as f:
                f.write(json.dumps(self.conf))
        except:
            pass

    def get(self, key, default=None):
        return self.conf.get(key, default)

    def set(self, key, value):
        self.conf[key] = value
        self.save()


class SegmentationApp(AIBase):
    def __init__(self, kmodel_path, labels, model_input_size, confidence_threshold=0.2, nms_threshold=0.5, mask_threshold=0.5, rgb888p_size=[224,224], display_size=[1920,1080], debug_mode=0):
        super().__init__(kmodel_path, model_input_size, rgb888p_size, debug_mode)
        self.kmodel_path = kmodel_path
        self.labels = labels
        self.model_input_size = model_input_size
        self.confidence_threshold = confidence_threshold
        self.nms_threshold = nms_threshold
        self.mask_threshold = mask_threshold
        self.rgb888p_size = [ALIGN_UP(rgb888p_size[0],16), rgb888p_size[1]]
        self.display_size = [ALIGN_UP(display_size[0],16), display_size[1]]
        self.debug_mode = debug_mode
        self.color_four = [
            (255, 220, 20, 60), (255, 119, 11, 32), (255, 0, 0, 142), (255, 0, 0, 230),
            (255, 106, 0, 228), (255, 0, 60, 100), (255, 0, 80, 100), (255, 0, 0, 70),
            (255, 0, 0, 192), (255, 250, 170, 30), (255, 100, 170, 30), (255, 220, 220, 0),
            (255, 175, 116, 175), (255, 250, 0, 30), (255, 165, 42, 42), (255, 255, 77, 255),
            (255, 0, 226, 252), (255, 182, 182, 255), (255, 0, 82, 0), (255, 120, 166, 157)
        ]
        self.masks = np.zeros((1, self.display_size[1], self.display_size[0], 4))
        self.ai2d = Ai2d(debug_mode)
        self.ai2d.set_ai2d_dtype(nn.ai2d_format.NCHW_FMT, nn.ai2d_format.NCHW_FMT, np.uint8, np.uint8)

    def config_preprocess(self, input_image_size=None):
        with ScopedTiming("set preprocess config", self.debug_mode > 0):
            ai2d_input_size = input_image_size if input_image_size else self.rgb888p_size
            top, bottom, left, right = self.get_padding_param()
            self.ai2d.pad([0,0,0,0,top,bottom,left,right], 0, [114,114,114])
            self.ai2d.resize(nn.interp_method.tf_bilinear, nn.interp_mode.half_pixel)
            self.ai2d.build([1,3,ai2d_input_size[1],ai2d_input_size[0]], [1,3,self.model_input_size[1],self.model_input_size[0]])

    def postprocess(self, results):
        with ScopedTiming("postprocess", self.debug_mode > 0):
            seg_res = aidemo.segment_postprocess(
                results,
                [self.rgb888p_size[1], self.rgb888p_size[0]],
                self.model_input_size,
                [self.display_size[1], self.display_size[0]],
                self.confidence_threshold,
                self.nms_threshold,
                self.mask_threshold,
                self.masks
            )
            return seg_res

    def draw_result(self, ui_img, seg_res):
        with ScopedTiming("display_draw", self.debug_mode > 0):
            if seg_res and seg_res[0]:
                dets, ids, scores = seg_res[0], seg_res[1], seg_res[2]
                for i, det in enumerate(dets):
                    x1, y1, w, h = map(lambda x: int(round(x, 0)), det)
                    label_text = " %s %.2f" % (self.labels[int(ids[i])], scores[i])
                    color = self.get_color(int(ids[i]))
                    ui_img.draw_rectangle(x1, y1, w, h, color=color[1:], thickness=2)
                    ui_img.draw_string_advanced(x1, y1 - 20, 16, label_text, color=color[1:])

    def draw_mask(self, ui_img):
        mask_img = image.Image(self.display_size[0], self.display_size[1], image.ARGB8888, alloc=image.ALLOC_REF, data=self.masks)
        ui_img.copy_from(mask_img)

    def get_padding_param(self):
        dst_w = self.model_input_size[0]
        dst_h = self.model_input_size[1]
        ratio_w = float(dst_w) / self.rgb888p_size[0]
        ratio_h = float(dst_h) / self.rgb888p_size[1]
        ratio = ratio_w if ratio_w < ratio_h else ratio_h
        new_w = int(ratio * self.rgb888p_size[0])
        new_h = int(ratio * self.rgb888p_size[1])
        dw = (dst_w - new_w) / 2
        dh = (dst_h - new_h) / 2
        top = int(round(dh - 0.1))
        bottom = int(round(dh + 0.1))
        left = int(round(dw - 0.1))
        right = int(round(dw + 0.1))
        return top, bottom, left, right

    def get_color(self, x):
        idx = x % len(self.color_four)
        return self.color_four[idx]


class YoloSegDemo:
    def __init__(self, pl):
        self.pl = pl
        self.seg = None

    def exce_demo_init(self, confidence_threshold=0.2, nms_threshold=0.5, mask_threshold=0.5):
        rgb888p_size = self.pl.rgb888p_size
        display_size = self.pl.display_size
        kmodel_path = "/sdcard/kmodel/yolov8n_seg_320.kmodel"
        labels = [
            "person", "bicycle", "car", "motorcycle", "airplane", "bus", "train", "truck", "boat", "traffic light",
            "fire hydrant", "stop sign", "parking meter", "bench", "bird", "cat", "dog", "horse", "sheep", "cow",
            "elephant", "bear", "zebra", "giraffe", "backpack", "umbrella", "handbag", "tie", "suitcase", "frisbee",
            "skis", "snowboard", "sports ball", "kite", "baseball bat", "baseball glove", "skateboard", "surfboard",
            "tennis racket", "bottle", "wine glass", "cup", "fork", "knife", "spoon", "bowl", "banana", "apple",
            "sandwich", "orange", "broccoli", "carrot", "hot dog", "pizza", "donut", "cake", "chair", "couch",
            "potted plant", "bed", "dining table", "toilet", "tv", "laptop", "mouse", "remote", "keyboard",
            "cell phone", "microwave", "oven", "toaster", "sink", "refrigerator", "book", "clock", "vase",
            "scissors", "teddy bear", "hair drier", "toothbrush"
        ]
        self.seg = SegmentationApp(
            kmodel_path,
            labels=labels,
            model_input_size=[320, 320],
            confidence_threshold=confidence_threshold,
            nms_threshold=nms_threshold,
            mask_threshold=mask_threshold,
            rgb888p_size=rgb888p_size,
            display_size=display_size,
            debug_mode=0
        )
        self.seg.config_preprocess()

    def run(self, img):
        return self.seg.run(img)

    def draw_result(self, ui_img, seg_res):
        if seg_res and seg_res[0]:
            self.seg.draw_mask(ui_img)
        self.seg.draw_result(ui_img, seg_res)
