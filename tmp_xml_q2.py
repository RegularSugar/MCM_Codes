import zipfile,xml.etree.ElementTree as ET,re,datetime
p=r'D:\AAA数模\参赛材料\第二问\outputs\result2.xlsx'
ns={'m':'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
with zipfile.ZipFile(p) as z:
 for sn in ['xl/worksheets/sheet1.xml','xl/worksheets/sheet2.xml','xl/worksheets/sheet3.xml']:
  root=ET.fromstring(z.read(sn)); dim=root.find('m:dimension',ns); rows=root.findall('.//m:sheetData/m:row',ns)
  print(sn,dim.attrib['ref'],len(rows))
