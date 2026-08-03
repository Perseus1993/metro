# PM-029 Image2 数字资产生成 Prompt

- 版本：`pm029_image2_prompts.v1`
- 日期：2026-07-18
- 用途：为 `asset_manifest.v2` 外部数字资产建立可复用的三维建模参考板和视觉方向；Image2 输出是概念/切图参考，不是可直接运行的 GLB。
- 参考图1：`apps/station_visualizer/src/metro_station_visualizer/assets/facility_sprite_sheet.png`，只参考设施设计语言、材质和清晰的状态差异。
- 参考图2：`apps/station_visualizer/src/metro_station_visualizer/assets/station_base.png`，只参考现代中国城市轨道交通空间、灰白石材、不锈钢和深色导视的整体材质语言。
- 建议输出目录：`output/imagegen/pm029-digital-assets/`

## 共用总控 Prompt

```text
Use case: stylized-concept
Asset type: modular metro-station digital asset modeling reference sheet
Primary request: create a production-oriented reference sheet for one reusable metro-station asset family; show modular construction, consistent scale, clean silhouettes, and operational states that can later be authored as GLB assets and bound through a versioned asset manifest
Input images: Image 1 is a facility-design and material-style reference only; Image 2 is a station-environment and material-language reference only. Do not copy their layout, labels, station geometry, or exact objects.
Scene/backdrop: clean warm light-gray studio background with a restrained technical presentation grid; no station scene and no passengers
Style/medium: polished realistic 3D product visualization, professional transit equipment, physically plausible construction, slightly simplified for clear simulation playback at desktop scale
Composition/framing: one landscape reference board; large three-quarter hero view plus orthographic front, side, and top views; a separate row of operational-state variants; every object fully visible with generous spacing
Lighting/mood: neutral soft studio lighting, consistent across all views, readable edges and cavities
Color palette: brushed stainless steel, charcoal gray, off-white stone, black glass, restrained amber and blue status lights; no branding
Materials/textures: realistic but clean metal, safety glass, rubber, painted steel, anti-slip flooring; no excessive grime
Constraints: modular and reusable; geometry must not imply a fixed station topology or fixed facility count; state differences must be physically coherent; consistent proportions across all views; no people; no station background; no perspective collage that hides structure; no logos; no watermark; no decorative copy
Avoid: sci-fi styling, airport styling, luxury showroom styling, impossible mechanics, random cables, baked station names, baked floor numbers, fixed six-elevator banks, tiny unreadable labels
```

## DA-01 电梯模块资产板（首轮执行）

```text
Use case: stylized-concept
Asset type: modular metro-station elevator GLB modeling reference sheet
Primary request: design one reusable accessible metro-station elevator asset family for a topology-driven passenger-flow simulation. The asset must be instanced independently for 0, 1, 3, or 6 physical elevators and support multiple floors without changing the model identity.
Input images: Image 1 is a facility-design and material-style reference only; Image 2 is a station-environment and material-language reference only. Do not copy their composition, text, or exact elevator.
Scene/backdrop: clean warm light-gray studio background with subtle panel divisions, no station scene
Subject: a modern through-floor metro elevator broken into clearly understandable modules: external door frame and landing facade, two sliding door leaves, visible cabin, shallow shaft surround, call-button panel, replaceable floor/status display panel, threshold, and a simple optional glass side panel. Show a large three-quarter closed-door hero view; front, side, and top orthographic views; an exploded modular view; and four coherent state variants: doors closed, doors opening, doors fully open with cabin visible, and out-of-service with an amber status light. The floor number area must remain blank and replaceable by runtime texture.
Style/medium: polished realistic 3D product visualization, professional Chinese urban metro equipment, modeling reference rather than advertising photography
Composition/framing: landscape technical asset board, consistent scale and proportions across views, every module fully visible, generous spacing
Lighting/mood: neutral soft studio lighting with clear metal and glass definition
Color palette: brushed stainless steel, charcoal gray, black glass, off-white stone surround, restrained amber and blue indicators
Materials/textures: brushed metal, safety glass, rubber door seals, anti-slip cabin floor, painted steel
Constraints: one reusable elevator family, not a fixed elevator bank; mechanically plausible two-leaf sliding doors; accessible proportions; clean topology-neutral silhouette; blank display; no people; no station background; no baked floor number; no Chinese or English text; no labels; no logos; no watermark
Avoid: sci-fi elevator, hotel elevator, ornate decoration, visible brand, impossible door motion, multiple unrelated designs, fixed B1/B2 markings, embedded station geometry
```

## DA-02 扶梯模块资产板

```text
Use case: stylized-concept
Asset type: modular metro-station escalator GLB modeling reference sheet
Primary request: create a reusable metro escalator kit made of top landing, bottom landing, and repeatable middle segments so different connector lengths can be assembled without uniformly stretching one model
Subject: one coherent escalator family with moving steps, comb plates, balustrades, handrails, landing lights, and direction indicator panels; show up, down, stopped, and out-of-service states using the same geometry
Composition/framing: large three-quarter view, side/front/top orthographic views, exploded top-middle-bottom modules, state row
Constraints: direction is a runtime state, not a separate baked model; no people; no fixed floor labels; no text; no logos; no watermark; topology-neutral
Avoid: paired escalators fused into one inseparable object, impossible step loop, fixed shaft length, shopping-mall ornament
```

## DA-03 楼梯模块资产板

```text
Use case: stylized-concept
Asset type: modular metro-station stair GLB modeling reference sheet
Primary request: create a reusable stair kit with top landing, bottom landing, repeatable tread section, side walls, dual-height handrails, tactile warning strips, and optional central divider
Composition/framing: three-quarter view, side/front/top orthographic views, exploded modular construction, normal and closed states
Constraints: repeatable middle section; metre-plausible proportions; closure shown by a removable barrier rather than changing topology; no text; no people; no logos; no watermark
Avoid: monumental decorative staircase, impossible riser proportions, fixed number of steps
```

## DA-04 闸机单通道资产板

```text
Use case: stylized-concept
Asset type: modular metro-station fare-gate lane GLB modeling reference sheet
Primary request: create one single-lane fare gate that can be repeated into arbitrary gate-bank capacity; include body, sensor panels, card reader, flap barriers, direction indicator, and removable wide-lane side module
Composition/framing: three-quarter hero view, front/side/top orthographic views, exploded lane module, state row showing entry, exit, bidirectional, closed, and fault using lights and barrier position
Constraints: one lane only; direction and state are runtime-driven material/animation variants; no baked arrows containing text; no passengers; no logos; no watermark
Avoid: fixed six-lane bank, airport security gate, waist-high tripod turnstile, brand-specific design
```

## DA-05 付费区隔离与临时屏障资产板

```text
Use case: stylized-concept
Asset type: modular metro-station barrier GLB modeling reference sheet
Primary request: create a modular barrier kit containing straight glass fare-barrier section, corner, end post, removable closure gate, temporary water-filled barrier, and folding service-closure barrier
Composition/framing: coherent kit in three-quarter and orthographic views with assembly examples
Constraints: modules must connect cleanly and leave gate openings controlled by topology; no fixed floor plan; no warning text; no logos; no watermark
Avoid: continuous barrier baked around a station, police barricade styling, unsafe sharp edges
```

## DA-06 出入口模块资产板

```text
Use case: stylized-concept
Asset type: modular metro-station entrance portal GLB modeling reference sheet
Primary request: create a reusable indoor station entrance/exit portal kit with side posts, overhead frame, optional glass doors, replaceable number panel, and runtime open/closed indicator
Composition/framing: three-quarter, front/side/top views, exploded frame modules, open and closed states
Constraints: blank replaceable sign panel; width assembled from modules; no baked station name or entrance number; no people; no logos; no watermark
Avoid: outdoor landmark pavilion, shopping-mall storefront, fixed station architecture
```

## DA-07 站台屏蔽门资产板

```text
Use case: stylized-concept
Asset type: modular metro platform-screen-door GLB modeling reference sheet
Primary request: create full-height platform screen door modules consisting of sliding-door pair, fixed glass panel, equipment/end post, and emergency door; modules repeat along any platform length
Composition/framing: large three-quarter module, front/side/top orthographic views, exploded pieces, closed/open/fault states
Constraints: runtime-controlled door animation; no train or passengers; no baked line name; no text; no logos; no watermark
Avoid: one fixed platform wall, inconsistent door widths, impossible overlapping glass
```

## DA-08 地铁列车模块资产板

```text
Use case: stylized-concept
Asset type: modular metro train GLB modeling reference sheet
Primary request: create a generic modern metro train kit with cab car, repeatable middle car, inter-car connection, and door module; line color must be a replaceable material parameter
Composition/framing: three-quarter train set, side/front/top orthographic views, exploded cab-middle-tail modules, stopped doors-closed, doors-open, and moving states
Constraints: generic original design; no operator logo; blank destination display; no baked line name; no passengers; no watermark
Avoid: high-speed train, national rail train, exact real-world operator livery, fixed train length
```

## DA-09 基础建筑材质与模块板

```text
Use case: stylized-concept
Asset type: metro-station modular environment and tileable material reference sheet
Primary request: create a coherent kit of seamless concourse floor, platform floor, tactile paving, platform warning strip, wall panel, square column, track bed, rail, and drainage edge
Composition/framing: clean material swatches plus small modular geometry samples, neutral orthographic presentation
Constraints: seamless tileable surfaces; no complete station scene; no signage text; no branding; no watermark
Avoid: unique focal stains, baked shadows, fixed platform geometry, ornate materials
```

## DA-10 状态贴花与诊断图形板

```text
Use case: stylized-concept
Asset type: runtime facility-state decal reference sheet
Primary request: create a compact, high-contrast family of topology-neutral status symbols for open, closed, up, down, bidirectional, stopped, reversing, fault, congestion, and service outage
Style/medium: clean transit pictograms suitable for emissive materials and 2D fallback overlays
Composition/framing: consistent square cells on a neutral background, large simple silhouettes, no prose text
Color palette: green open/down, amber warning/reversing, red closed/fault, blue information, neutral inactive
Constraints: original symbols; readable at small size; no logos; no alphabetic or Chinese text; no watermark
Avoid: decorative icon set, gradients that reduce legibility, inconsistent stroke weight
```

## P1 后续组合包

P1不在首轮调用中，待P0视觉语言稳定后再拆分为：设备包、服务空间包、商业门面包、家具/障碍物包和安全设施包。每个对象必须通过 `visual_kind` 选择，不能只依赖宽泛的 `equipment/shop/obstacle` kind。

## 执行顺序

1. DA-01 电梯；
2. DA-02 扶梯与DA-03楼梯；
3. DA-04闸机与DA-05隔离设施；
4. DA-07站台门与DA-08列车；
5. DA-06出入口、DA-09环境材质、DA-10状态图形；
6. P1环境组合包。

每轮只改变一个资产家族；通过后再把被接受的视觉语言写回下一轮Prompt，避免不同设施各自形成一套风格。

## 执行记录

### 2026-07-18 / DA-01

- 执行路径：内置Image2图像生成；
- 输入参考：设施素材表、站厅材质参考图；
- 首版检查：模块拆解、正侧顶视图和四种门状态满足方向；自动产生的三个英文视图标签不符合无文字约束；
- 单点修订：仅移除 `Front / Side / Top`，其余构图和设施保持；
- 最终产物：`output/imagegen/pm029-digital-assets/DA-01_elevator_modular_reference_v1.png`；
- SHA256：`26A699D7156EAD3974B3B181303F8B9BAB2D4C1E16DAA0943A9869BAD76AF70C`；
- 状态：`generated concept reference / not a GLB / not integrated into asset_manifest.v2`。
