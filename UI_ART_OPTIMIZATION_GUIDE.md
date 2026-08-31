# DeskCamdio UI 美术优化指导书

> 基线：GitHub `main@8366a87`（2026-08-31）  
> 目标设备：Raspberry Pi Zero 2 W、480×480 触摸屏  
> 目标：在不牺牲流畅度和可读性的前提下，把现有界面统一为可量产、可扩展的“口袋水族馆系统”。

## 1. 当前视觉审查结论

最新版本已经具备统一圆角、主题 Token、海洋背景、线性图标和截图工具，但距离商业化仍有以下差距：

1. 像素鱼、水草、现代线性图标和大面积白色卡片来自不同视觉体系，混搭感明显。
2. 相册、备忘、GBA、PS1 等空状态重复使用“白卡片 + 线性图标 + 同一海底”，应用辨识度不足。
3. Launcher 第三页只有 PS1，一个 2×2 页面仅放一个入口，视觉重心失衡。
4. GBA 与 PS1 页面结构几乎完全相同，只靠标题区分；游戏平台缺少封面、最近游玩和手柄状态等识别信息。
5. 钓鱼港口采用现代扁平卡片，出海后切换为高密度像素画，HUD 造型也不一致。
6. `fish` 与 `graphite` 都是深色海洋主题，差异主要是强调色，主题价值不够明确。
7. Camera、Settings、Pomodoro 等工具页面较干净，但组件高度、留白、主次按钮和图标使用不完全统一。
8. `fishpi-badge-source.png` 带烘焙棋盘背景和“豆包AI生成”水印，只能作为开发参考，不能发布。

## 2. 统一艺术方向

### 2.1 核心概念：Pocket Aquarium OS

采用“精密系统 UI + 16-bit 水族世界”的双层语言：

- **系统层**：代码绘制的几何卡片、清晰文字、统一 Tabler 线性图标、稳定焦点与状态色。
- **世界层**：鱼、植物、气泡、海床和钓鱼场景使用严格像素画。
- 系统层不得伪装成像素 UI；像素画也不得使用平滑缩放。两层边界明确后，混搭会变成产品特色。
- 视觉性格：安静、友好、精致、略带掌机感；不幼儿化、不赛博朋克、不堆高光和玻璃模糊。

### 2.2 形状与层级

- 基础网格：8px；允许4px半格用于图标和细节。
- 页面安全区：左右16px；顶部内容从16px开始；底部交互区至少留12px。
- 圆角：小控件12px、普通卡片18px、主卡片24px、胶囊按钮高度的一半。
- 描边：1px常规，焦点环3px；不使用多层发光边。
- 阴影：只允许2px向下的低透明度硬阴影，或用深一级 Surface 表达层级；不实时模糊。
- 最小点击区48×48；主操作按钮不小于96×48。

### 2.3 字体层级

统一使用内置 Noto Sans SC，数字计时可使用同字体粗体：

| 角色 | 字号 | 字重 | 用途 |
|---|---:|---|---|
| Display | 52–68 | Bold | 时间、番茄钟、拍摄倒计时 |
| H1 | 24 | Bold | 页面标题 |
| H2 | 20 | Bold | 卡片标题、空状态标题 |
| Body | 17 | Regular | 正文、列表主文字 |
| Label | 15 | Medium | 按钮、标签、状态 |
| Caption | 13–14 | Regular | 辅助说明、设备信息 |

规则：一页最多出现4级字号；英文缩写和中文基线对齐；不把AI生成文字烘焙进图片。

### 2.4 主题策略

保留4个主题，但分别承担明确场景：

| 主题 | 定位 | 建议主色 | 使用方式 |
|---|---|---|---|
| Aquatic | 默认日间 | `#2076C4` | 清爽蓝灰、低对比海底 |
| Fish | 锦鲤夜间 | `#E24444` | 暖黑、珊瑚红、米白，不再像石墨主题 |
| Cream | 暖光桌面 | `#E27A2E` | 奶油背景、焦糖沙地、柔和蓝水 |
| Graphite | 专注模式 | `#7A84E8` | 冷石墨、蓝紫强调、尽量减少彩色装饰 |

所有主题共用布局和资产轮廓。系统图标运行时染色；像素资产只允许少量经过审核的调色板变体，不能为每个主题生成完全不同造型。

## 3. 页面级优化

### 3.1 待机页

- 保留“时间 + 当前音乐 + 水族箱 + 三个摘要 + 语音入口”的信息架构。
- 主鱼固定在视觉中心下方，陪伴鱼缩小并降低饱和度，避免三条鱼争夺焦点。
- 水草集中在底部80px，不能穿入摘要卡片。
- 波纹和气泡透明度降低30%，背景只做氛围，不干扰文字。
- 音乐卡缩为单行状态卡；没有音乐时不显示大面积空卡，只显示轻量胶囊。
- 语音按钮成为唯一高强调主按钮，其余摘要卡只用中性 Surface。

### 3.2 Launcher

- 9个应用改为单页3×3网格，消除第三页孤立PS1入口。
- 网格建议：x=`24/176/328`，y=`76/190/304`，单元128×98，水平间距24，垂直间距16。
- 图标32px，标签15px；选中状态为3px强调色焦点环和轻微抬升，不改变图标形状。
- 应用分色仅用于小型角标：相机蓝、音乐紫、游戏青、钓鱼橙、工具中性；卡片主体仍跟随主题。
- 页面标题使用“应用”，Fish品牌标记放入顶部状态区，避免“Fish 应用”中英文层级含混。

### 3.3 相机与相册

- 相机采用深色沉浸式预览区，预览框不再使用厚白边；仅保留1px描边和4个轻量取景角标。
- 底部控制坞统一高度72px：左侧相册入口、中间64px快门、右侧滤镜；分辨率作为顶部小胶囊。
- 相机不可用时使用暗色预览区内的设备错误插画，不让错误文本孤零零悬在黑屏中央。
- 相册空状态使用“小照片漂浮在气泡中”的专属插画；有照片时采用2列缩略图，不叠加海底装饰。

### 3.4 音乐、备忘、番茄钟

- 音乐页增加唱片/气泡专属插画和播放状态视觉，不再复用通用白卡。
- 备忘空状态使用“漂流瓶 + 小纸条”，新增内容仍用代码文字和按钮完成。
- 番茄钟保持极简，不添加海底插画；用环形进度、状态色和轻微呼吸动画表达专注状态。
- 三个工具页共享标题、按钮和弹窗组件，但插画只服务空状态，不侵入操作页。

### 3.5 GBA 与 PS1

- 两个平台共用 Game Library 组件，不共用主视觉：
  - GBA：青绿色、通用掌机卡带、像素点阵背景。
  - PS1：靛蓝色、通用光盘盒和光盘，不使用Sony、PlayStation图形商标。
- 空状态插画控制在160×112内，下方显示导入路径和手柄状态。
- 有游戏时使用封面缩略图 + 标题 + 最近游玩；无封面时由代码生成平台色占位封面。
- 启动前页显示控制器、存档、内存和退出方式；游戏运行中不叠加复杂装饰。
- 禁止AI生成任天堂、索尼角色、Logo、主机外观复刻或游戏封面。

### 3.6 钓鱼

- 港口继续使用系统卡片，但加入同一套像素鱼、仓库箱和小船作为装饰锚点。
- 出海场景的所有鱼统一到同一像素比例、同一左上光源、同一1px深紫轮廓。
- HUD改为系统层胶囊：左上返回、右上体力/鱼饵、右侧收线；不再混用不同圆角和透明度。
- 海面、远景、鱼层、前景水草分层，保证钓线和目标鱼在灰度下也清晰。

### 3.7 设置与系统覆盖层

- 设置保留4个标签页；每行增加统一的24px前导图标和明确状态色。
- 设备名、内存值等动态信息使用右对齐Caption；操作按钮不与状态文字重叠。
- 危险操作统一红色确认弹窗；重启、关机、退出应用的插画不使用AI生成文字。
- 系统覆盖层使用高对比、低装饰的系统风格，不能铺海草或动态鱼。

## 4. 资产生产规格

| 资产族 | 输出规格 | 调色板/透明度 | 运行时处理 |
|---|---|---|---|
| 主鱼与陪伴鱼 | 单帧64×64；每动作4帧 | 每条≤16色；Alpha仅0/255 | 最近邻整数倍缩放 |
| 钓鱼鱼种 | 48×32或64×48 | 统一1px深紫轮廓 | 最近邻缩放 |
| 水草/珊瑚/贝壳 | 32×48或64×64 | 每件≤12色；透明背景 | 底部中心锚点 |
| 空状态插画 | 160×112 | 最多24色；可有少量半透明气泡 | 原尺寸或整数倍 |
| 海洋背景层 | 480×480分层PNG | 低对比；透明前中景 | 预载、禁止每帧缩放 |
| 游戏库占位封面 | 96×128 | 平台色 + 几何图案 | 标题由代码绘制 |
| 装饰纹样 | 48×48无缝Tile | 2–4色 | 低Alpha平铺 |
| 功能图标 | 24/32px矢量源 | 单色 | 继续使用统一Tabler族 |

功能图标、文字、按钮、进度条、焦点环和弹窗必须代码绘制，不交给图像模型生成。

## 5. AI生成工作流

1. 先生成一张480×480风格目标板，只用于批准方向，不直接入库。
2. 生成一条主鱼的单帧种子；在真实待机页背景上按最终显示尺寸审核。
3. 以批准种子为参考图生成同一动作的4帧候选，再由脚本切片、对齐和清色。
4. 同一家族每次只生成3–6件，必须复用种子、调色板、视角和光照描述。
5. 每个PNG经过尺寸、Alpha、颜色数、边缘、锚点和许可证记录检查。
6. 真正像素画必须人工或脚本清除伪像素、半透明边缘、单像素噪点和不一致色簇。
7. 在480×480真实页面截图中验收，不以放大后的单张图片作为通过依据。

## 6. 通用提示词卡

以下英文块作为所有生成任务的固定前缀，`[SUBJECT]`替换为具体资产：

```text
ROLE/PURPOSE: production candidate art for a 480x480 Raspberry Pi desktop companion UI named Fish.
SUBJECT: [SUBJECT]
VIEW: strict 2D orthographic side/front view as specified, centered, consistent scale.
ART DIRECTION: premium pocket-aquarium operating system; true 16-bit pixel art for world objects; compact friendly silhouettes; one-pixel dark indigo outline; controlled color clusters; soft top-left light; calm aquatic palette; restrained detail that reads at native size.
GAME-SCALE READ: the silhouette and primary state must remain immediately recognizable when displayed at 48-96 pixels.
TECHNICAL OUTPUT: exact requested canvas, transparent background, isolated object, no cropped pixels, no drop shadow outside the canvas.
LOCKS: preserve camera angle, proportions, outline color and width, palette roles, top-left lighting, baseline, and padding across the entire asset family.
EXCLUDE: text, letters, numbers, logos, trademarks, signatures, watermarks, mockup frames, photorealism, 3D rendering, gradients, soft antialiasing, blurry edges, excessive texture, random particles, duplicate objects, checkerboard baked into the image.
```

像素资产通用负面提示词：

```text
no pseudo-pixel art, no mixed pixel sizes, no semi-transparent edge pixels, no painterly brushwork, no neon cyberpunk, no glossy mobile-game rendering, no thick black cartoon outline, no perspective distortion, no copyrighted character likeness
```

## 7. 分资产AI提示词

### 7.1 视觉目标板（只作参考）

```text
Create a 480x480 visual direction board for a premium pocket aquarium operating system.
Show one hero fish, two companion fish, a small seabed vegetation family, a generic handheld game cartridge, a camera motif, one neutral UI card fragment, and a compact semantic palette.
The world art is true 16-bit pixel art; the UI chrome is clean geometric vector-like design with rounded rectangles and consistent thin line icons.
Use calm blue-grey water, warm sand, dark indigo outlines, and one coral accent. Keep all functional labels blank. Demonstrate clear separation between decorative pixel art and precise system UI.
This is an art-direction reference, not a final screenshot and not a functional UI mockup.
```

### 7.2 主鱼单帧种子

```text
[Use the common prompt card]
SUBJECT: one friendly blue aquarium companion fish, left-facing side view, oversized readable head, compact body, small tail clearly separated from the silhouette, alert but calm expression.
TECHNICAL OUTPUT: 64x64 transparent PNG candidate, fish occupies about 50x32 pixels, bottom-center anchor, at least 6 pixels clear padding on every side, maximum 16 colors, alpha only fully opaque or fully transparent.
PALETTE: deep indigo outline #332B67, body blues #4567D8 #5D8EF2 #8DBAF8, belly highlight #C8E3FF, eye #101522, one optional coral cheek pixel cluster #E45C67.
```

### 7.3 主鱼游动4帧

必须把批准的单帧作为参考图输入：

```text
Using the attached approved fish seed as an exact identity reference, create four candidate frames of a subtle looping swim cycle in one horizontal strip.
Frame 1 matches the approved neutral pose. Frames 2-4 move only the tail, rear fins and body by a maximum of two source pixels. Preserve head shape, eye position, body volume, outline, palette, baseline and canvas padding exactly. No squash of the head and no change of facing.
OUTPUT CANDIDATE: four 64x64 cells in a 256x64 transparent strip. No separators, labels or guide marks.
```

生成后必须重新切片，并用原始种子覆盖第1帧。

### 7.4 水草与海底装饰家族

```text
[Use the common prompt card]
SUBJECT: a coherent family of three small aquarium plants and one shell: one slender seaweed, one broad-leaf plant, one compact coral-like bush, and one closed clam. Each object has a distinct silhouette and a shared top-left light direction.
TECHNICAL OUTPUT: isolated transparent candidates, each designed for a 32x48 or 64x64 canvas with bottom-center ground contact, maximum 12 colors per object.
PALETTE: olive green #547A35, leaf green #75A947, highlight #A9CF62, shadow indigo #313858, warm shell #C49352 #E5BD72.
EXCLUDE: sand base attached to every object, floating roots, photorealistic leaves, dense noise, bright neon green.
```

### 7.5 分层水族背景

分别生成远景、中景、前景，不要求模型一次正确输出分层文件：

```text
Create a horizontally seamless 480x480 pixel-art aquarium environment plate for a calm desktop companion.
Composition: the upper 300 pixels remain low-detail open water for text and fish; the seabed occupies only the bottom 80 pixels; decorative plants stay away from the center and UI safe zones; no large landmark near the left or right seam.
Lighting is soft from the top-left. Use broad controlled color bands rather than gradients. The playfield must remain low contrast behind dark and bright fish.
No fish, no UI, no text, no bubbles, no frame, no vignette.
```

随后人工拆为：远景水色、波纹中景、海床与植物前景，并做3×3平铺检查。

### 7.6 空状态插画模板

每个应用单独生成，保持同一参考种子：

```text
[Use the common prompt card]
SUBJECT: [one of: a small photo floating inside a bubble / a message in a glass bottle / a music record with two bubbles / a generic green handheld cartridge / a generic indigo optical disc case / a sleeping focus timer].
COMPOSITION: one centered object plus no more than three tiny bubbles; generous negative space; friendly but not childish.
TECHNICAL OUTPUT: 160x112 transparent PNG candidate, subject within 120x80, maximum 24 colors.
EXCLUDE: words, console logos, brand marks, game characters, realistic product replicas, white card background, button shapes.
```

### 7.7 GBA通用卡带占位图

```text
[Use the common prompt card]
SUBJECT: a generic compact handheld game cartridge viewed straight-on, rounded top corners, simple recessed label area containing only abstract wave and bubble geometry.
TECHNICAL OUTPUT: 96x128 transparent PNG candidate, teal and navy palette, no readable text.
EXCLUDE: Nintendo branding, Game Boy shape replication, copyrighted game art, labels, ratings, barcodes.
```

### 7.8 PS1通用光盘盒占位图

```text
[Use the common prompt card]
SUBJECT: a generic square optical disc case and a partially visible iridescent disc, front three-quarter arrangement but with minimal perspective, abstract aquarium wave artwork on the insert.
TECHNICAL OUTPUT: 96x128 transparent PNG candidate, indigo, slate and cyan palette, no readable text.
EXCLUDE: PlayStation or Sony logos, controller button symbols, copyrighted cover art, realistic product photography.
```

### 7.9 钓鱼鱼种家族

```text
[Use the common prompt card]
SUBJECT: a coherent family of four catchable fish with clearly different silhouettes: slender common fish, round puffer-like fish, long rare fish, and angular deep-water fish. All left-facing, same baseline and pixel density.
TECHNICAL OUTPUT: each fish fits a 64x48 transparent canvas, one neutral swim pose per species, maximum 16 colors each.
RARITY LANGUAGE: common uses muted blue-grey, uncommon uses green-teal, rare uses warm gold, legendary uses deep coral with only two bright highlight clusters.
EXCLUDE: real-world species labels, weapons, crowns, glow halos, particle effects, different camera angles.
```

### 7.10 Fish品牌鱼形概念（不可直接作为Logo）

```text
Create twelve black-and-white concept silhouettes for a compact Fish brand emblem: a circular fish motion, one continuous tail gesture, friendly but precise, readable at 16mm physical size and 24px screen size.
Flat solid shapes only, no text, no gradients, no mockup, no trademark resemblance, no surrounding badge.
```

选中概念后必须人工重绘为SVG/代码路径；AI位图不得直接成为正式Logo。

## 8. 动效规范

- 页面切换：200ms，标准ease-out；低内存模式立即切换。
- 卡片按下：80ms内填充色变深，不做全卡缩放造成文字抖动。
- 焦点移动：120ms焦点环位置插值；手柄操作必须始终可见焦点。
- 主鱼游动：6–8 FPS源动画，屏幕30 FPS更新位置；不要生成30 FPS逐帧素材。
- 气泡：最多8个，轨迹确定性复用；禁止每帧创建Surface。
- 错误提示不抖屏；只使用一次150ms色彩强调。

## 9. 验收门槛

### 视觉

- 在480×480原尺寸下，3秒内能识别当前页面、主操作和状态。
- 所有功能图标来自同一线性图标族；不存在描边、填充、3D和像素图标混用。
- 像素资产只有统一源像素尺寸，最近邻缩放后无模糊或半像素位置。
- 四主题下正文、辅助文字、焦点环和危险状态均满足清晰对比。
- 每个空状态有应用辨识度，但不抢过标题和主按钮。

### 技术

- 每个正式资产记录来源、许可证、尺寸、用途、Alpha和审核状态。
- PNG尺寸、调色板、透明通道、锚点和命名由脚本检查。
- AI输出必须保留生成记录和编辑记录；带签名、水印或来源不明的文件禁止发布。
- 480×480截图覆盖正常、空、加载、错误、断连、低内存和存储不足状态。
- 新资产加载后，冷启动RSS和页面P95帧时间不得突破既有预算。

## 10. 推荐实施顺序

1. **建立风格目标板**：先批准主鱼、植物、空状态和一段UI的组合效果。
2. **统一系统层**：字体、3×3 Launcher、按钮、卡片、焦点、空状态布局。
3. **生产世界资产**：主鱼与植物，再扩展钓鱼鱼种和背景层。
4. **区分应用**：相册、音乐、备忘、GBA、PS1空状态插画和平台色。
5. **统一动效**：焦点、页面切换、鱼动画、错误反馈和低内存降级。
6. **四主题验收**：逐页截图、联系表、真机观察距离测试和性能回归。

正式批量生成前，只批准一张风格目标板和一条主鱼种子。未通过这两个门槛，不继续生成完整素材库。

## 11. 美术资产交付状态（2026-08-31）

本指导书对应的AI位图候选库已经完成，位于 `art/generated/`：

- 30张原始生成图，保留被替换的v1/v2版本用于溯源。
- 76个规范化资产，覆盖主鱼与动作、陪伴鱼、水草海床、四主题背景、空状态、摄像头故障、手柄状态、低内存、存储不足、GBA/PS1、钓鱼流程、品牌标记和启动页。
- 功能图标、文字、控件、焦点环、进度条和弹窗继续由代码绘制，不属于AI位图资产缺口。
- `art/generated/asset-manifest.csv`记录尺寸、透明度、用途、主题、源文件、生成方式、许可证和审核状态。
- `art/generated/processed/generated-assets-contact-sheet-v1.png`用于完整视觉验收。
- `scripts/process_generated_art.py`可重复生成原生尺寸资产；`scripts/qa_generated_art.py`检查清单、尺寸、空图、源文件和Alpha。

当前自动验收结果为76/76文件通过，63个RGBA文件全部使用0/255二值Alpha。资产已通过懒加载方式接入真实Pygame页面，并完成480×480无头模拟、逐页截图与wheel打包测试；下一阶段只需在Pi Zero 2 W真机上完成帧时间、RSS、屏幕观感和主题对比度验收。
