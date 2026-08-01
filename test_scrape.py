import requests
from bs4 import BeautifulSoup
import pandas as pd

# 20260731 is a valid trading Friday in our timeline
url = 'https://finance.naver.com/sise/investorDealTrendDay.nhn?bizdate=20260731&sosok=&page=1'
headers = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
}

r = requests.get(url, headers=headers)
r.encoding = 'euc-kr'
print("Response Status Code:", r.status_code)
print("Length of content:", len(r.text))

soup = BeautifulSoup(r.text, 'html.parser')
tb = soup.find('table', class_='type_1')
if tb:
    rows = tb.find_all('tr')
    print("Number of rows found:", len(rows))
    for i, tr in enumerate(rows):
        cells = [td.text.strip().replace('\n', '').replace('\t', '') for td in tr.find_all(['td', 'th'])]
        cells = [c for c in cells if c]
        if cells:
            print(f"Row {i}: {cells}")
else:
    print("Table type_1 not found!")
