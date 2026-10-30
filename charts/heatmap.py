import seaborn as sns
import matplotlib.pyplot as plt
import io
import base64

def generate_heatmap(df):
    heatmap_data = df.groupby(['day', 'hour']).size().unstack(fill_value=0)
    fig, ax = plt.subplots(figsize=(12, 5))
    sns.heatmap(heatmap_data, cmap="Blues", ax=ax)
    buf = io.BytesIO()
    fig.savefig(buf, format="png")
    buf.seek(0)
    encoded = base64.b64encode(buf.read()).decode("utf-8")
    return f"data:image/png;base64,{encoded}"
