import tushare

print(tushare.__version__)

pro = tushare.pro_api('ec5e80be23eece512899bd7ce9cd468287f2a52f113a6d3230e48f45')

df = df = pro.tmt_twincome(item='8', start_date='20120101', end_date='20181010')
print(df)