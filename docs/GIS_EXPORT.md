# ขั้นตอน Export GIS → GeoJSON ให้พิกัดตรงแผนที่ PEA SPARK

## สาเหตุที่พิกัดคลาด (เดิม)

แอปแปลงพิกัดจากระบบ **UTM โซน 47N (เมตร)** ไป **WGS84 (Lat/Lon)** สำหรับแสดงบน OpenStreetMap

- ไฟล์ `.prj` ในโฟลเดอร์ `data` ระบุ **WGS 84 / UTM Zone 47N** → ใช้ **EPSG:32647**
- หากตั้งค่าในโค้ดเป็น EPSG:24047 (Indian 1975) สายจะเลื่อนบนแผนที่หลายร้อยเมตร

ตรวจ/แก้ที่ `data/network_config.json`:

```json
"sourceCrs": "EPSG:32647"
```

---

## ใน QGIS (แนะนำ)

1. เปิด shapefile จาก PEA / GIS ต้นทาง
2. คลิกขวาชั้นข้อมูล → **Properties** → **Source** → ดู CRS  
   ต้องเป็น **WGS 84 / UTM zone 47N** (หรือตรงกับที่ใช้จริง)
3. หาก CRS ผิด: **Layer** → **Export** → **Save Features As…**
   - Format: **GeoJSON**
   - CRS: **EPSG:32647** (หรือ EPSG ตาม .prj จริง — **อย่า** export เป็น 4326 แล้วให้แอปแปลงซ้ำ)
4. เก็บพิกัด geometry เป็น **พิกัดฉาก (x,y เป็นเมตร)** ไม่ใช่ lat/lon
5. วางไฟล์ใน `data/` แล้วอัปเดตชื่อใน `network_config.json` → `layers`

---

## ตรวจหลัง Export

1. เปิด `*.json` ดู `coordinates` ของ LineString — ค่า x ประมาณ **400,000–900,000** y ประมาณ **1,000,000–1,500,000** (พื้นที่ประจวบ) = UTM เมตร ถูกต้อง  
2. หาก x,y อยู่ในช่วง **99–100 และ 11–13** = เป็น WGS84 อยู่แล้ว → ตั้ง `"sourceCrs": "EPSG:4326"` และปรับโค้ดให้ไม่แปลงซ้ำ (ต้องแก้ app เฉพาะกรณีนี้)
3. รีสตาร์ท `python app.py` หลังเปลี่ยน config

---

## ชื่อไฟล์ในโฟลเดอร์ data

แก้รายการใน `data/network_config.json` ใต้ `layers` ให้ตรงชื่อไฟล์จริง เช่น:

```json
"conductors": ["conducps.json"],
"switches": ["dofps.json"],
"reclosers": ["recloserps.json"],
"transformers": ["transps.json"],
"substations": ["cball.json"]
```

ไม่ต้องแก้ `app.py` ถ้าชื่ออยู่ใน config นี้
