<template>
  <div class="api-ref">
    <h3>📖 API 参考</h3>

    <section>
      <h4>可用变量</h4>
      <ul>
        <li><code>data</code> — K线数据数组，每项包含: <code>time</code>, <code>open</code>, <code>high</code>, <code>low</code>, <code>close</code>, <code>volume</code></li>
        <li><code>positions</code> — 当前持仓数组，每项包含: <code>direction</code>, <code>entryPrice</code>, <code>entryTime</code></li>
        <li><code>bar</code> — 当前K线对象</li>
        <li><code>bars</code> — 全部K线数组</li>
        <li><code>position</code> — 当前净持仓数量（正=多，负=空）</li>
      </ul>
    </section>

    <section>
      <h4>返回值（每根K线调用一次）</h4>
      <div class="code-block">
        <div><span class="key">{ action</span>: <span class="str">'buy'</span>, <span class="key">price</span>: xxx, <span class="key">reason</span>: <span class="str">'xxx'</span> } — 买入开多</div>
        <div><span class="key">{ action</span>: <span class="str">'sell'</span>, <span class="key">price</span>: xxx, <span class="key">reason</span>: <span class="str">'xxx'</span> } — 卖出平多</div>
        <div><span class="key">{ action</span>: <span class="str">'short'</span>, <span class="key">price</span>: xxx, <span class="key">reason</span>: <span class="str">'xxx'</span> } — 卖出开空</div>
        <div><span class="key">{ action</span>: <span class="str">'cover'</span>, <span class="key">price</span>: xxx, <span class="key">reason</span>: <span class="str">'xxx'</span> } — 买入平空</div>
        <div><span class="key">{ action</span>: <span class="str">'hold'</span> } — 持有不变</div>
      </div>
    </section>

    <section>
      <h4>内置函数</h4>
      <table class="func-table">
        <tr><td><code>sma(period, index)</code></td><td>简单移动平均</td></tr>
        <tr><td><code>ema(period, index)</code></td><td>指数移动平均</td></tr>
        <tr><td><code>macd(fast, slow, signal)</code></td><td>MACD指标</td></tr>
        <tr><td><code>rsi(period, index)</code></td><td>RSI指标</td></tr>
        <tr><td><code>bollinger(period, stddev, index)</code></td><td>布林带指标</td></tr>
        <tr><td><code>atr(period, index)</code></td><td>平均真实波幅</td></tr>
      </table>
    </section>

    <section>
      <h4>内置变量（可直接使用）</h4>
      <table class="func-table">
        <tr><td><code>open</code></td><td>当前K线开盘价</td></tr>
        <tr><td><code>high</code></td><td>当前K线最高价</td></tr>
        <tr><td><code>low</code></td><td>当前K线最低价</td></tr>
        <tr><td><code>close</code></td><td>当前K线收盘价</td></tr>
        <tr><td><code>volume</code></td><td>当前K线成交量</td></tr>
        <tr><td><code>prev_bar</code></td><td>上一根K线（含 open/high/low/close/volume）</td></tr>
        <tr><td><code>entry_price</code></td><td>当前持仓开仓均价（0=无持仓）</td></tr>
      </table>
    </section>

    <section>
      <h4>策略示例 — EMA+RSI 只做多</h4>
      <pre class="example">{{ exampleCode }}</pre>
      <button class="copy-btn" @click="copyExample">📋 复制示例</button>
    </section>
  </div>
</template>

<script setup lang="ts">
const exampleCode = `# EMA+RSI 策略 - 只做多
def strategy(data, positions, bar, bars):
    c = bar['close']
    h = bar['high']
    l = bar['low']
    v = bar['volume']
    
    ema_fast = ema(12)
    ema_slow = ema(26)
    rsi_val = rsi(14)
    
    # 入场：EMA金叉 + RSI > 50 + 放量
    if position <= 0 and ema_fast > ema_slow and rsi_val > 50:
        return { 'action': 'buy', 'price': c, 'reason': f'金叉+RSI{rsi_val:.0f}' }
    
    # 出场：死叉 或 RSI < 30
    if position > 0 and (ema_fast < ema_slow or rsi_val < 30):
        return { 'action': 'sell', 'price': c, 'reason': f'出场 RSI{rsi_val:.0f}' }
    
    return { 'action': 'hold' }`

function copyExample() {
  navigator.clipboard.writeText(exampleCode)
}
</script>

<style scoped>
.api-ref {
  padding: 16px 20px;
  max-width: 800px;
}

.api-ref h3 {
  font-size: 18px;
  margin-bottom: 16px;
  color: #333;
}

.api-ref h4 {
  font-size: 15px;
  color: #1890ff;
  margin: 14px 0 8px;
}

.api-ref section {
  margin-bottom: 16px;
}

.api-ref ul {
  padding-left: 20px;
}

.api-ref li {
  margin: 4px 0;
  font-size: 14px;
  line-height: 1.6;
  color: #444;
}

.api-ref code {
  background: #f0f2f5;
  padding: 1px 5px;
  border-radius: 3px;
  font-family: 'Fira Code', monospace;
  font-size: 13px;
  color: #e83e8c;
}

.code-block {
  background: #f6f8fa;
  border: 1px solid #e8e8e8;
  border-radius: 6px;
  padding: 12px 16px;
  font-family: 'Fira Code', monospace;
  font-size: 13px;
  line-height: 1.8;
}

.code-block .key { color: #d73a49; }
.code-block .str { color: #032f62; }

.func-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 14px;
}

.func-table td {
  padding: 6px 12px;
  border-bottom: 1px solid #f0f0f0;
}

.func-table td:first-child {
  width: 280px;
  font-family: 'Fira Code', monospace;
  font-size: 13px;
  color: #e83e8c;
}

.func-table td:last-child {
  color: #555;
}

.example {
  background: #1e1e1e;
  color: #d4d4d4;
  padding: 14px 16px;
  border-radius: 6px;
  overflow-x: auto;
  font-size: 13px;
  line-height: 1.6;
  font-family: 'Fira Code', monospace;
}

.copy-btn {
  margin-top: 8px;
  padding: 4px 12px;
  border: 1px solid #d9d9d9;
  border-radius: 4px;
  background: #fff;
  cursor: pointer;
  font-size: 13px;
  color: #333;
}

.copy-btn:hover {
  border-color: #1890ff;
  color: #1890ff;
}
</style>
