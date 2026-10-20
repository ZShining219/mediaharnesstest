# 商品 Profile

每个商品一份 JSON，链路不再把商品常量写进代码。

最少字段：

```json
{
  "product_id": "",
  "image": "data/.../product.jpg",
  "category": "",
  "identity": "",
  "must_show": [],
  "must_not_change": [],
  "claims": [],
  "proofs": [],
  "default_archetype": "ugc_individual_seller",
  "color_policy": "single|same_style_multi",
  "person": {
    "image": "assets/persons/...",
    "side_image": "assets/persons/...",
    "identity": "",
    "immutable": [],
    "policy": "",
    "authorization": "self_owned|licensed|unknown"
  },
  "constraints": {
    "platform": "douyin",
    "claims_avoid": [],
    "compliance_notes": []
  }
}
```

可选字段：
- `reference_id`：该商品在参考池里的商品来源案例；
- `description`：给 prompt 的商品描述；
- `back_image`：商品背面图，侧身/背影车道会额外提交给 H3，避免背面被拍成光面基础款；
- `inner_image`：商品内里图，内里/软支撑证明使用；
- `allowed_person_visibility`：允许的人物呈现，默认四种都允许；内裤等不适合上身的品类可设为 `["hands_only","none"]`；
- `offer`：价格/活动占位；
- `reference_policy`：商品图使用说明。

人物可选 `side_image`：侧身/背影车道使用侧脸图，减少正面参考把模型拉回正脸口播。

Profile 是**配置**，不是 pool 描述；pool 仍然独立、全量描述视频。
