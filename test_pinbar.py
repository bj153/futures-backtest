import akshare as ak

df = ak.futures_main_sina(symbol='JM0')
df = df.tail(35)

df['body'] = abs(df['close'] - df['open'])
df['upper_wick'] = df['high'] - df[['open', 'close']].max(axis=1)
df['lower_wick'] = df[['open', 'close']].min(axis=1) - df['low']
df['wick_range'] = df['high'] - df['low']
df['small_body'] = df['body'] < df['wick_range'] * 0.4

# 用 and 替代 &
df['bullish_pin'] = (df['lower_wick'] > df['body'] * 1.5) & df['small_body'] & (df['close'] > (df['high'] + df['low']) / 2)
df['bearish_pin'] = (df['upper_wick'] > df['body'] * 1.5) & df['small_body'] & (df['close'] < (df['high'] + df['low']) / 2)

print('看涨Pin Bar:', df['bullish_pin'].sum())
print('看跌Pin Bar:', df['bearish_pin'].sum())

for i, row in df[df['bullish_pin'] | df['bearish_pin']].iterrows():
    pin_type = '看涨' if row['bullish_pin'] else '看跌'
    print(f"{row['date'].strftime('%m-%d')} {pin_type}Pin: 开{row['open']:.0f} 高{row['high']:.0f} 低{row['low']:.0f} 收{row['close']:.0f}")