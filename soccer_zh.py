"""
五大聯賽以外的足球隊中文名（台灣常用譯名；冷門球隊用音譯）。隊名依 Pinnacle／Action Network 的寫法。
沒有的就顯示英文。國家隊在 NATIONS。
"""

CLUBS = {
    # 阿甲
    "Aldosivi": "阿爾多西維", "Argentinos Juniors": "阿根廷青年人", "Atletico Tucuman": "圖庫曼競技", "Banfield": "班菲爾德",
    "Barracas Central": "巴拉卡斯中央", "Belgrano": "貝爾格拉諾", "Boca Juniors": "博卡青年", "CA Independiente": "獨立隊",
    "CA Tigre": "老虎隊", "Central Cordoba": "科爾多瓦中央", "Defensa y Justicia": "國防與司法", "Deportivo Riestra": "里耶斯特拉",
    "Estudiantes Rio Cuarto": "里奧誇爾托學生", "Estudiantes de La Plata": "拉普拉塔學生", "Gimnasia La Plata": "拉普拉塔體操",
    "Gimnasia Mendoza": "門多薩體操", "Huracan": "颶風隊", "Independiente Rivadavia": "里瓦達維亞獨立", "Instituto": "學院隊",
    "Lanus": "拉努斯", "Newells Old Boys": "紐維爾老男孩", "Platense": "普拉騰斯", "Racing Club": "競賽俱樂部", "River Plate": "河床",
    "Rosario Central": "羅薩里奧中央", "San Lorenzo": "聖羅倫佐", "Sarmiento de Junin": "薩米恩托", "Talleres de Cordoba": "科爾多瓦塔勒瑞斯",
    "Union de Santa Fe": "聖塔菲聯", "Velez Sarsfield": "薩斯菲爾德",
    # 澳職
    "Adelaide United": "阿德雷德聯", "Auckland FC": "奧克蘭FC", "Brisbane Roar": "布里斯本獅吼", "Central Coast Mariners": "中央海岸水手",
    "Macarthur FC": "麥克阿瑟", "Melbourne City": "墨爾本城", "Melbourne Victory": "墨爾本勝利", "Newcastle Jets": "紐卡索噴射機",
    "Perth Glory": "珀斯光榮", "Sydney FC": "雪梨FC", "Wellington Phoenix": "威靈頓鳳凰", "Western Sydney Wanderers": "西雪梨流浪者",
    # 奧超
    "Austria Lustenau": "盧斯特瑙", "Austria Vienna": "維也納奧地利", "Grazer AK": "格拉茨AK", "Hartberg": "哈特貝格", "LASK Linz": "林茨LASK",
    "Linzer Athletik-Sport-Klub": "林茨LASK", "Rapid Vienna": "維也納快速", "SCR Altach": "阿爾塔赫", "SV Ried": "里德", "Salzburg": "薩爾斯堡",
    "Sturm Graz": "格拉茨風暴", "WSG Tirol": "蒂羅爾", "Wolfsberger AC": "沃夫斯貝格",
    # 比甲
    "Anderlecht": "安德萊赫特", "Beveren": "貝弗倫", "Cercle Brugge": "布魯日瑟克", "Charleroi": "沙勒羅瓦", "Club Brugge": "布魯日",
    "Genk": "亨克", "Gent": "根特", "KV Kortrijk": "科特賴克", "KVC Westerlo": "韋斯特洛", "Lommel": "洛默爾", "Mechelen": "梅赫倫",
    "Oud-Heverlee Leuven": "魯汶", "RAAL La Louviere": "拉盧維耶爾", "Royal Antwerp": "安特衛普", "Sint Truidense": "聖圖爾登",
    "Standard Liege": "標準列日", "Union Saint-Gilloise": "聖吉羅斯聯", "Union St.Gilloise": "聖吉羅斯聯", "Zulte Waregem": "瓦勒海姆",
    # 巴甲
    "Athletico Paranaense": "巴拉納競技", "Atletico Mineiro": "米內羅競技", "Bahia": "巴伊亞", "Botafogo FR RJ": "博塔弗戈",
    "Bragantino": "布拉甘蒂諾", "Chapecoense": "沙佩科恩斯", "Corinthians": "科林蒂安", "Coritiba": "科里蒂巴", "Cruzeiro": "克魯塞羅",
    "Flamengo": "佛朗明哥", "Fluminense": "弗魯米嫩塞", "Gremio": "格雷米奧", "Internacional": "國際體育會", "Mirassol": "米拉索爾",
    "Palmeiras": "帕梅拉斯", "Remo": "雷莫", "Santos": "桑托斯", "Sao Paulo": "聖保羅", "Vasco da Gama": "達伽馬", "Vitoria": "維多利亞",
    # 德甲／德國盃
    "Freiburg": "弗萊堡", "Schalke 04": "沙爾克04", "Bochum": "波鴻", "Darmstadt": "達姆施塔特", "Dynamo Dresden": "德勒斯登迪納摩",
    "FC Magdeburg": "馬德堡", "Hannover 96": "漢諾威96", "Hertha BSC": "柏林赫塔", "Holstein Kiel": "基爾", "Jeddeloh": "耶德洛",
    "Kaiserslautern": "凱澤斯勞滕", "Karlsruher": "卡爾斯魯厄", "Nurnberg": "紐倫堡", "Rot-Weiss Essen": "埃森紅白",
    "Sonnenhof Grossaspach": "格羅薩斯帕赫", "Stuttgart": "斯圖加特", "Wolfsburg": "沃夫斯堡",
    # 英冠／英聯賽盃
    "Birmingham City": "伯明罕", "Blackburn Rovers": "布萊克本", "Bolton Wanderers": "博爾頓", "Bristol City": "布里斯托城",
    "Cardiff City": "卡地夫城", "Charlton Athletic": "查爾頓", "Derby County": "德比郡", "Lincoln City": "林肯城", "Middlesbrough": "米德爾斯堡",
    "Millwall": "米爾沃爾", "Norwich City": "諾里奇", "Portsmouth": "朴茨茅斯", "Preston North End": "普雷斯頓", "Queens Park Rangers": "女王公園巡遊者",
    "Stoke City": "史托克城", "Swansea City": "斯旺西", "Watford": "華特福", "West Bromwich Albion": "西布朗", "Wolverhampton": "狼隊",
    "Wrexham": "雷克斯漢姆", "Bournemouth": "伯恩茅斯", "Bradford City": "布拉德福德", "Brighton": "布萊頓", "Fleetwood Town": "弗利特伍德",
    "Peterborough United": "彼得堡聯",
    # 中超
    "Beijing Guoan": "北京國安", "Chengdu Rongcheng": "成都蓉城", "Chongqing Tonglianglong": "重慶銅梁龍", "Dalian Yingbo": "大連英博",
    "Henan": "河南", "Liaoning Tieren": "遼寧鐵人", "Qingdao Hainiu": "青島海牛", "Qingdao West Coast": "青島西海岸", "Shandong Taishan": "山東泰山",
    "Shanghai Port": "上海海港", "Shanghai Shenhua": "上海申花", "Shenzhen Peng City": "深圳新鵬城", "Tianjin Jinmen Tiger": "天津津門虎",
    "Wuhan Three Towns": "武漢三鎮", "Yunnan Yukun": "雲南玉昆", "Zhejiang": "浙江",
    # 丹超
    "AGF": "奧胡斯", "Brondby": "布隆德比", "FC Copenhagen": "哥本哈根", "FC Nordsjaelland": "北西蘭", "Horsens": "霍森斯", "Lyngby": "靈比",
    "Midtjylland": "中日德蘭", "Odense BK": "歐登塞", "Randers": "蘭德斯", "Silkeborg": "錫爾克堡", "Sonderjyske": "南日德蘭", "Viborg": "維堡",
    # 荷甲
    "ADO Den Haag": "海牙", "AZ Alkmaar": "阿爾克馬爾", "Ajax": "阿賈克斯", "Cambuur Leeuwaarden": "坎布爾", "Excelsior": "精英隊",
    "FC Twente": "特溫特", "FC Utrecht": "烏特勒支", "Feyenoord": "費耶諾德", "Fortuna Sittard": "錫塔德", "Go Ahead Eagles": "前進之鷹",
    "Groningen": "格羅寧根", "Heerenveen": "海倫芬", "NEC Nijmegen": "奈梅亨", "PEC Zwolle": "茲沃勒", "PSV": "PSV燕豪芬",
    "PSV Eindhoven": "PSV燕豪芬", "Sparta Rotterdam": "鹿特丹斯巴達", "Telstar": "特爾斯達", "Willem II": "威廉二世",
    # 希超
    "AEK Athens": "雅典AEK", "Aris Thessaloniki": "阿里斯", "Asteras Tripolis": "特里波利", "Atromitos": "阿特羅米托斯",
    "Iraklis 1908 FC": "伊拉克利斯", "Kalamata": "卡拉馬塔", "Kifisia": "基菲西亞", "Levadiakos": "利華迪亞高斯", "OFI Crete": "克里特OFI",
    "Olympiakos": "奧林匹亞科斯", "Olympiacos": "奧林匹亞科斯", "PAOK": "PAOK", "Panathinaikos": "帕納辛納克斯", "Panetolikos": "帕內托利科斯",
    "Volos": "沃洛斯",
    # 日本J聯賽
    "Avispa Fukuoka": "福岡黃蜂", "Cerezo Osaka": "大阪櫻花", "FC Tokyo": "FC東京", "Fagiano Okayama": "岡山綠雉", "Gamba Osaka": "大阪飛腳",
    "JEF United Chiba": "千葉市原", "Kashima Antlers": "鹿島鹿角", "Kashiwa Reysol": "柏雷素爾", "Kawasaki Frontale": "川崎前鋒",
    "Kyoto Sanga": "京都不死鳥", "Machida Zelvia": "町田澤維亞", "Mito HollyHock": "水戶蜀葵", "Nagoya Grampus": "名古屋鯨八",
    "Sanfrecce Hiroshima": "廣島三箭", "Shimizu S-Pulse": "清水心跳", "Tokyo Verdy": "東京綠茵", "Urawa Red Diamonds": "浦和紅鑽",
    "V-Varen Nagasaki": "長崎成功丸", "Vissel Kobe": "神戶勝利船", "Yokohama F. Marinos": "橫濱水手",
    # 韓國K聯賽
    "Anyang": "安養", "Bucheon FC 1995": "富川", "Daejeon Citizen": "大田市民", "FC Seoul": "FC首爾", "Gangwon FC": "江原",
    "Gimcheon Sangmu": "金泉尚武", "Gwangju FC": "光州", "Incheon United": "仁川聯", "Jeju SK": "濟州SK", "Jeonbuk Motors": "全北現代",
    "Pohang Steelers": "浦項制鐵", "Ulsan HD": "蔚山HD",
    # 沙烏地聯賽
    "Abha Club": "阿布哈", "Al Diriyah": "迪里耶", "Al-Ahli": "吉達國民", "Al-Ettifaq": "協作隊", "Al-Faisaly": "費薩利", "Al-Fateh": "法塔赫",
    "Al-Fayha": "費哈", "Al-Hazem": "哈茲姆", "Al-Hilal": "利雅德新月", "Al-Ittihad": "吉達聯合", "Al-Khaleej": "海灣隊", "Al-Kholood": "胡盧德",
    "Al-Nassr": "利雅德勝利", "Al-Qadisiyah": "卡迪西亞", "Al-Riyadh": "利雅德", "Al-Shabab": "青年人", "Al-Taawoun": "合作隊", "Neom": "尼歐姆",
    # 西甲／法甲（原本沒有的）
    "Levante UD": "萊萬特", "Racing Santander": "桑坦德競技", "Troyes": "特魯瓦",
    # 墨超
    "Atlante": "亞特蘭特", "Atlas": "阿特拉斯", "Atletico San Luis": "聖路易斯競技", "Club America": "美洲隊", "Club Tijuana": "蒂華納",
    "Cruz Azul": "藍十字", "Deportivo Toluca": "托盧卡", "FC Juarez": "華雷斯", "Monterrey": "蒙特雷", "Necaxa": "內卡薩", "Pachuca": "帕丘卡",
    "Puebla": "普埃布拉", "Pumas UNAM": "美洲獅", "Santos Laguna": "桑托斯拉古納",
    # 美國MLS
    "Atlanta United": "亞特蘭大聯", "Austin FC": "奧斯汀FC", "CF Montreal": "蒙特婁", "Charlotte FC": "夏洛特FC", "Chicago Fire": "芝加哥火焰",
    "Colorado Rapids": "科羅拉多急流", "Columbus Crew": "哥倫布機員", "DC United": "DC聯", "FC Cincinnati": "辛辛那提", "FC Dallas": "達拉斯FC",
    "Houston Dynamo FC": "休士頓迪納摩", "Inter Miami CF": "邁阿密國際", "LA Galaxy": "洛杉磯銀河", "Los Angeles FC": "洛杉磯FC",
    "Minnesota United": "明尼蘇達聯", "Nashville SC": "納許維爾", "New England Revolution": "新英格蘭革命", "New York City FC": "紐約城",
    "New York Red Bulls": "紐約紅牛", "Orlando City": "奧蘭多城", "Philadelphia Union": "費城聯", "Portland Timbers": "波特蘭伐木者",
    "Real Salt Lake": "皇家鹽湖城", "San Diego FC": "聖地牙哥FC", "San Jose Earthquakes": "聖荷西地震", "Seattle Sounders FC": "西雅圖海灣人",
    "Sporting Kansas City": "堪薩斯城體育", "St. Louis City": "聖路易城", "Toronto FC": "多倫多FC", "Vancouver Whitecaps": "溫哥華白浪",
    # 挪超
    "Aalesunds": "奧勒松", "Bodo Glimt": "博德閃耀", "Bodoe/Glimt": "博德閃耀", "Brann": "布蘭", "Fredrikstad": "腓特烈斯塔", "Ham-Kam": "哈姆坎",
    "KFUM Oslo": "奧斯陸KFUM", "Kristiansund": "克里斯蒂安松", "Lillestrom": "利勒斯特倫", "Lillestroem": "利勒斯特倫", "Molde": "莫爾德",
    "Rosenborg": "羅森博格", "Sandefjord": "桑德菲傑", "Sarpsborg 08": "薩爾普斯堡", "Start": "斯塔特", "Tromso": "特羅姆瑟",
    "Valerenga": "瓦勒倫加", "Viking": "維京",
    # 葡超
    "Academico de Viseu": "維塞烏學院", "Alverca": "阿爾韋卡", "Arouca": "阿羅卡", "Benfica": "本菲卡", "Braga": "布拉加", "Casa Pia": "卡薩皮亞",
    "Estoril": "埃斯托里爾", "Estrela da Amadora": "阿馬多拉之星", "Famalicao": "法馬利康", "Gil Vicente": "吉爾維森特", "Maritimo": "馬里迪莫",
    "Moreirense": "莫雷倫斯", "Nacional da Madeira": "馬德拉國民", "Porto": "波爾圖", "FC Porto": "波爾圖", "Rio Ave": "里奧阿維",
    "Santa Clara": "聖克拉拉", "Sporting CP": "葡萄牙體育", "Vitoria Guimaraes": "吉馬良斯", "Torreense": "托雷斯",
    # 俄超
    "Akhmat Grozny": "格羅茲尼艾哈邁德", "Akron Togliatti": "陶里亞蒂阿克隆", "Baltika Kaliningrad": "加里寧格勒波羅的海", "CSKA Moscow": "莫斯科中央陸軍",
    "Dynamo Makhachkala": "馬哈奇卡拉迪納摩", "Dynamo Moscow": "莫斯科迪納摩", "Fakel Voronezh": "沃羅涅日火炬", "Krasnodar": "克拉斯諾達爾",
    "Krylia Sovetov": "薩馬拉蘇維埃之翼", "Lokomotiv Moscow": "莫斯科火車頭", "Orenburg": "奧倫堡", "Rodina Moscow": "莫斯科羅迪納",
    "Rostov": "羅斯托夫", "Rubin Kazan": "喀山紅寶石", "Spartak Moscow": "莫斯科斯巴達", "Zenit": "澤尼特",
    # 蘇超
    "Aberdeen": "亞伯丁", "Celtic": "塞爾提克", "Dundee FC": "鄧迪", "Dundee United": "鄧迪聯", "Falkirk": "福爾柯克", "Hearts": "哈茨",
    "Hibernian": "希伯尼安", "Kilmarnock": "基爾馬諾克", "Motherwell": "馬瑟韋爾", "Rangers": "格拉斯哥流浪者", "St Johnstone": "聖約翰斯通",
    "St Mirren": "聖米倫",
    # 瑞士超
    "Basel": "巴塞爾", "FC Lugano": "盧加諾", "FC Luzern": "琉森", "FC Vaduz": "瓦杜茲", "FC Zurich": "蘇黎世", "Grasshopper Club Zurich": "草蜢",
    "Lausanne-Sport": "洛桑", "Servette": "塞爾維特", "Sion": "錫永", "St. Gallen": "聖加侖", "Thun": "圖恩", "Young Boys": "年輕人",
    # 瑞典超
    "AIK": "AIK索爾納", "Brommapojkarna": "布洛馬波卡納", "Degerfors": "德格佛斯", "Djurgardens": "尤爾加登", "Elfsborg": "埃爾夫斯堡",
    "GAIS": "GAIS哥德堡", "Hacken": "赫根", "Halmstads": "哈爾姆斯塔德", "Hammarby": "哈馬比", "IFK Goteborg": "哥德堡", "Kalmar": "卡爾馬",
    "Malmo": "馬爾默", "Mjallby": "米亞爾比", "Orgryte": "厄格里特", "Sirius": "天狼星", "Vasteras": "韋斯特羅斯",
    # 土超
    "Alanyaspor": "阿拉尼亞", "Amedspor": "阿梅德", "Besiktas": "貝西克塔斯", "Caykur Rizespor": "里澤", "Corum Belediyespor": "喬魯姆",
    "Erzurumspor": "埃爾祖魯姆", "Eyupspor": "埃尤普", "Fenerbahce": "費內巴切", "Galatasaray": "加拉塔沙雷", "Gaziantep": "加濟安泰普",
    "Genclerbirligi": "根克勒比利吉", "Goztepe": "格茲特佩", "Istanbul Basaksehir": "伊斯坦堡巴沙克塞希爾", "Kasimpasa": "卡瑟姆帕夏",
    "Kocaelispor": "科賈埃利", "Konyaspor": "科尼亞", "Samsunspor": "薩姆松", "Trabzonspor": "特拉布宗",
    # 歐洲賽事其他球隊
    "Sabah FK": "薩巴赫", "Shakhtar Donetsk": "頓內茨克礦工", "Slavia Prague": "布拉格斯拉維亞", "Slovan Bratislava": "布拉提斯拉瓦斯洛萬",
    "Borac Banja Luka": "巴尼亞盧卡博拉茨", "CSKA Sofia": "索菲亞中央陸軍", "Crvena Zvezda": "貝爾格勒紅星", "Egnatia Rrogozhine": "埃格納蒂亞",
    "Hajduk Split": "斯普利特海杜克", "Iberia 1999": "伊比利亞1999", "Inter Club d'Escaldes": "埃斯卡爾德國際", "Jablonec": "亞布洛內茨",
    "Kairat Almaty": "阿拉木圖凱拉特", "Kauno Zalgiris": "考納斯薩爾基利斯", "KuPS": "庫奧皮奧", "Lincoln Red Imps": "林肯紅魔",
    "Pafos": "帕福斯", "Riga FC": "里加FC", "Universitatea Craiova": "克拉約瓦大學", "Ararat-Armenia": "阿拉拉特亞美尼亞",
    "Dinamo Zagreb": "薩格勒布迪納摩", "Ferencvaros": "費倫茨瓦羅斯", "Hapoel Beer Sheva": "貝爾謝巴夏普爾", "Jagiellonia Bialystok": "比亞韋斯托克",
    "Lech Poznan": "波茲南萊赫", "Levski Sofia": "索菲亞列夫斯基", "NK Celje": "采列", "Omonia Nicosia": "尼科西亞奧莫尼亞",
    "Sparta Prague": "布拉格斯巴達", "Viktoria Plzen": "皮爾森勝利", "Montevideo City Torque": "蒙特維多城",
}

NATIONS = {
    "Argentina": "阿根廷", "Brazil": "巴西", "France": "法國", "England": "英格蘭", "Spain": "西班牙", "Portugal": "葡萄牙", "Germany": "德國",
    "Netherlands": "荷蘭", "Belgium": "比利時", "Italy": "義大利", "Croatia": "克羅埃西亞", "Uruguay": "烏拉圭", "Colombia": "哥倫比亞",
    "Morocco": "摩洛哥", "Switzerland": "瑞士", "Denmark": "丹麥", "Japan": "日本", "USA": "美國", "United States": "美國", "Mexico": "墨西哥",
    "Senegal": "塞內加爾", "Austria": "奧地利", "Ukraine": "烏克蘭", "Sweden": "瑞典", "Norway": "挪威", "Poland": "波蘭", "Serbia": "塞爾維亞",
    "Turkey": "土耳其", "Türkiye": "土耳其", "Ecuador": "厄瓜多", "Iran": "伊朗", "South Korea": "南韓", "Korea Republic": "南韓", "Australia": "澳洲",
    "Wales": "威爾斯", "Scotland": "蘇格蘭", "Northern Ireland": "北愛爾蘭", "Republic of Ireland": "愛爾蘭", "Ireland": "愛爾蘭",
    "Czech Republic": "捷克", "Czechia": "捷克", "Hungary": "匈牙利", "Slovakia": "斯洛伐克", "Slovenia": "斯洛維尼亞", "Romania": "羅馬尼亞",
    "Greece": "希臘", "Russia": "俄羅斯", "Finland": "芬蘭", "Iceland": "冰島", "Albania": "阿爾巴尼亞", "Bosnia and Herzegovina": "波士尼亞",
    "Bosnia-Herzegovina": "波士尼亞", "North Macedonia": "北馬其頓", "Montenegro": "蒙特內哥羅", "Georgia": "喬治亞", "Armenia": "亞美尼亞",
    "Azerbaijan": "亞塞拜然", "Kazakhstan": "哈薩克", "Israel": "以色列", "Cyprus": "賽普勒斯", "Bulgaria": "保加利亞", "Belarus": "白俄羅斯",
    "Lithuania": "立陶宛", "Latvia": "拉脫維亞", "Estonia": "愛沙尼亞", "Luxembourg": "盧森堡", "Malta": "馬爾他", "Moldova": "摩爾多瓦",
    "Kosovo": "科索沃", "Faroe Islands": "法羅群島", "Andorra": "安道爾", "San Marino": "聖馬利諾", "Liechtenstein": "列支敦斯登",
    "Gibraltar": "直布羅陀", "Peru": "秘魯", "Chile": "智利", "Paraguay": "巴拉圭", "Venezuela": "委內瑞拉", "Bolivia": "玻利維亞",
    "Canada": "加拿大", "Costa Rica": "哥斯大黎加", "Panama": "巴拿馬", "Jamaica": "牙買加", "Honduras": "宏都拉斯", "El Salvador": "薩爾瓦多",
    "Guatemala": "瓜地馬拉", "Haiti": "海地", "Curaçao": "古拉索", "Curacao": "古拉索", "Trinidad and Tobago": "千里達", "Suriname": "蘇利南",
    "Saudi Arabia": "沙烏地阿拉伯", "Qatar": "卡達", "Iraq": "伊拉克", "United Arab Emirates": "阿聯", "UAE": "阿聯", "Oman": "阿曼",
    "Jordan": "約旦", "Uzbekistan": "烏茲別克", "China PR": "中國", "China": "中國", "Chinese Taipei": "中華台北", "Taiwan": "中華台北",
    "Hong Kong": "香港", "Thailand": "泰國", "Vietnam": "越南", "Indonesia": "印尼", "Malaysia": "馬來西亞", "Philippines": "菲律賓",
    "Singapore": "新加坡", "India": "印度", "North Korea": "北韓", "Korea DPR": "北韓", "Bahrain": "巴林", "Kuwait": "科威特", "Syria": "敘利亞",
    "Lebanon": "黎巴嫩", "Palestine": "巴勒斯坦", "Kyrgyzstan": "吉爾吉斯", "Tajikistan": "塔吉克", "New Zealand": "紐西蘭",
    "Egypt": "埃及", "Nigeria": "奈及利亞", "Ghana": "迦納", "Cameroon": "喀麥隆", "Ivory Coast": "象牙海岸", "Côte d'Ivoire": "象牙海岸",
    "Algeria": "阿爾及利亞", "Tunisia": "突尼西亞", "Mali": "馬利", "Burkina Faso": "布吉納法索", "South Africa": "南非", "DR Congo": "剛果民主共和國",
    "Cape Verde": "維德角", "Guinea": "幾內亞", "Gabon": "加彭", "Zambia": "尚比亞", "Angola": "安哥拉", "Benin": "貝南", "Uganda": "烏干達",
    "Kenya": "肯亞", "Equatorial Guinea": "赤道幾內亞", "Mozambique": "莫三比克", "Libya": "利比亞", "Sudan": "蘇丹", "Togo": "多哥",
    "Madagascar": "馬達加斯加", "Zimbabwe": "辛巴威", "Namibia": "納米比亞", "Tanzania": "坦尚尼亞", "Mauritania": "茅利塔尼亞",
    "Sierra Leone": "獅子山", "Gambia": "甘比亞", "Comoros": "葛摩", "Rwanda": "盧安達", "Botswana": "波札那", "Ethiopia": "衣索比亞",
}
