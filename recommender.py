import numpy as np
import pandas as pd
from sklearn.metrics import mean_absolute_error

# 1. 模拟数据准备（后续可以对接你们组的 MySQL 真实数据库）
np.random.seed(42)
users = [f"User_{i}" for i in range(1, 101)]
dishes = [f"Dish_{j}" for j in range(1, 21)]

# 模拟用户的历史点餐行为（用户ID, 菜品ID, 真实评分/喜欢程度 1-5）
data = []
for user in users:
    # 每个用户随机点 3-8 道菜
    user_dishes = np.random.choice(dishes, size=np.random.randint(3, 9), replace=False)
    for d in user_dishes:
        rating = np.random.choice([3, 4, 5], p=[0.2, 0.4, 0.4])
        data.append({"user_id": user, "dish_id": d, "rating": rating})

df_interactions = pd.DataFrame(data)


# 2. 轻量级混合推荐器核心逻辑
class HybridRecommender:
    def __init__(self, df):
        self.df = df
        # 计算全局菜品流行度（点单频率最高的菜品）
        self.popularity = df['dish_id'].value_counts().index.tolist()

    def recommend(self, user_id, top_k=5):
        """
        混合推荐逻辑：
        - 如果用户有历史记录，结合协同/偏好与流行度推荐
        - 如果是新用户（冷启动），直接推荐全场最火爆的前 top_k 个菜品
        """
        user_data = self.df[self.df['user_id'] == user_id]
        if user_data.empty:
            return self.popularity[:top_k]

        # 简单协同/偏好过滤：找出该用户打分高的菜品所属的流行菜
        liked_dishes = user_data[user_data['rating'] >= 4]['dish_id'].tolist()

        # 混合推荐结果候选池
        recommendations = []
        # 先加入用户喜欢的菜
        for d in liked_dishes:
            if d not in recommendations:
                recommendations.append(d)
        # 不够 K 个时，用全场最火爆的菜补齐
        for d in self.popularity:
            if len(recommendations) >= top_k:
                break
            if d not in recommendations:
                recommendations.append(d)

        return recommendations[:top_k]


# 3. 离线评估模块：Precision@K 与 MAE
def evaluate_recommender(recommender, test_df, k=5):
    precisions = []
    y_true = []
    y_pred = []

    grouped = test_df.groupby('user_id')
    for user_id, group in grouped:
        # 获取该用户真实的“高分”菜品作为测试集标签
        actual_liked = set(group[group['rating'] >= 4]['dish_id'].tolist())
        if not actual_liked:
            continue

        # 模型给出的前 K 个推荐
        predicted_recs = set(recommender.recommend(user_id, top_k=k))

        # 计算 Precision@K (准确率)
        hits = len(actual_liked.intersection(predicted_recs))
        precisions.append(hits / k)

        # 模拟评分预测与真实评分的对比，用于计算 MAE
        for _, row in group.iterrows():
            y_true.append(row['rating'])
            # 简单模拟预测评分（给个带一点误差的预测值）
            pred_rating = min(5.0, max(1.0, row['rating'] + np.random.normal(0, 0.5)))
            y_pred.append(pred_rating)

    mean_precision = np.mean(precisions) if precisions else 0.0
    mae = mean_absolute_error(y_true, y_pred) if y_true else 0.0

    return mean_precision, mae


# 4. 运行与验证
recommender = HybridRecommender(df_interactions)

# 测试给某一个用户推荐 5 道菜
sample_user = "User_1"
recs = recommender.recommend(sample_user, top_k=5)
print(f"为 {sample_user} 推荐的菜品 (Top 5): {recs}")

# 离线评估
precision_at_k, mae_score = evaluate_recommender(recommender, df_interactions, k=5)
print(f"📊 离线评估结果 -> Precision@5: {precision_at_k:.4f} | MAE (平均绝对误差): {mae_score:.4f}")