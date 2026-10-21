"""S31 integrated QA. Writes ONE order only when --allow-order is explicitly set.
Never makes real payments, refunds, shipping labels, or deletes existing data.
"""
import argparse, datetime, json, os, re, sys
from pathlib import Path
from playwright.sync_api import sync_playwright

results=[]
def record(name, status, detail=''):
    results.append(dict(test=name,status=status,detail=str(detail)[:350]))
    print(status,name,str(detail)[:180],flush=True)

def js(page, expression):
    return page.evaluate(expression)

def db(page, table, fields='*', **filters):
    return page.evaluate('''async ({table,fields,filters})=>{
      if(typeof s31Client==='undefined'||!s31Client)throw Error('Supabase client unavailable');
      let q=s31Client.from(table).select(fields);
      for(const [k,v] of Object.entries(filters))q=q.eq(k,v);
      const r=await q.limit(100);if(r.error)throw Error(r.error.message);return r.data||[];
    }''',{'table':table,'fields':fields,'filters':filters})

def test(url,allow_order):
    user=os.getenv('S31_TEST_USERNAME','')
    pwd=os.getenv('S31_TEST_PASSWORD','')
    with sync_playwright() as p:
      browser=p.chromium.launch(headless=True)
      page=browser.new_page(viewport={'width':390,'height':844},locale='zh-TW')
      page.on('dialog',lambda d:d.dismiss() if d.type=='confirm' else d.accept())
      errors=[]
      page.on('pageerror',lambda e:errors.append(str(e)))
      order_id=None
      try:
        response=page.goto(url,wait_until='domcontentloaded',timeout=45000)
        record('網站 HTTP 正常','PASS' if response and response.ok else 'FAIL',response.status if response else '無回應')
        page.wait_for_timeout(3500)
        for pattern in ['Google Apps Script 網址','清理預設或殘留測試資料','確認不再加單・統整匯款金額','出貨滿 10 日自動']:
          record('舊文字已移除 '+pattern,'PASS' if pattern not in page.locator('body').inner_text() else 'FAIL')
        for selector in ['#topNavBtnHome','#topNavBtnLogin','#topNavBtnOrders','#admTab_orders','#admTab_products','#admTab_analytics','#admOrdTab_pending','#admOrdTab_bought','#admOrdTab_packing','#admOrdTab_shipped','#admOrdTab_completed']:
          record('必要元件 '+selector,'PASS' if page.locator(selector).count() else 'FAIL')
        page.screenshot(path='s31_mobile.png',full_page=True)
        page.set_viewport_size({'width':1365,'height':900})
        page.screenshot(path='s31_desktop.png',full_page=True)
        page.set_viewport_size({'width':390,'height':844})
        if not user or not pwd:
          record('登入','BLOCKED','缺少 GitHub Secrets')
          return
        page.locator('#topNavBtnLogin').click()
        page.locator('#memberModal').wait_for(state='visible')
        js(page,"switchAuthModalTab('account')")
        page.locator('#loginAccInput').fill(user)
        page.locator('#loginPwdInput').fill(pwd)
        page.locator('#btnSubmitAccLogin').click()
        page.wait_for_function("typeof s31SupabaseUser!=='undefined' && !!s31SupabaseUser && typeof memberToken!=='undefined' && !!memberToken",timeout=30000)
        record('會員登入','PASS')
        try:
          page.wait_for_function("typeof s31IsAdmin!=='undefined' && !!s31IsAdmin",timeout=20000)
          record('管理員角色','PASS')
        except Exception:record('管理員角色','FAIL','20 秒未載入')
        js(page,"switchMainView('shop')")
        try:
          page.locator('#topNavBtnOrders').wait_for(state='visible',timeout=20000)
          record('客人訂單入口','PASS')
        except Exception:record('客人訂單入口','FAIL')
        identity=js(page,"s31SupabaseUser.id")
        before=db(page,'orders','id,user_id,status,created_at',user_id=identity)
        record('本人訂單可讀取','PASS',f'{len(before)} 筆（最多100筆）')
        try:
          products=db(page,'products','id,name,price,is_active')
          record('商品資料庫可讀取','PASS',f'{len(products)} 筆（最多100筆）')
        except Exception as e:
          products=[];record('商品資料庫可讀取','WARNING',str(e))
        try:
          page.locator('#topNavBtnOrders').click(timeout=10000)
          record('我的訂單頁面開啟','PASS' if page.locator('#viewOrders').is_visible() else 'FAIL')
        except Exception as e:record('我的訂單頁面開啟','FAIL',str(e))
        js(page,"switchMainView('admin')")
        record('賣家後台開啟','PASS' if page.locator('#viewAdmin').is_visible() else 'FAIL')
        for tab in ['orders','products','analytics']:
          try:
            js(page,f"s31SwitchTab('{tab}')")
            record('後台分頁 '+tab,'PASS')
          except Exception as e:record('後台分頁 '+tab,'FAIL',str(e))
        if not allow_order:
          record('真實下單','BLOCKED','未啟用手動 allow_order；未寫入訂單')
          return
        # Explicitly require the same account and a stable candidate variant.
        js(page,"switchMainView('shop')")
        candidate=js(page,"""() => {
          if(typeof products==='undefined'||typeof s31VariantLookup==='undefined')return null;
          for(const p of products){
            if(p.isActive===false||p.active===false)continue;
            for(const [key,vid] of s31VariantLookup.entries()){
              const parts=String(key).split('|');
              if(String(parts[0])===String(p.id)&&vid&&Number(p.price)>0){
                return {id:p.id,name:p.name,color:parts[1]||'',size:parts[2]||'',price:Number(p.price),variant_id:vid};
              }
            }
          }
          return null;
        }""")
        if not candidate:
          record('建立測試訂單','BLOCKED','沒有找到可用且有價格的商品規格；為避免錯誤下單已停止')
          return
        record('測試商品規格可用','PASS',f"{candidate['name']} / {candidate['color']} / {candidate['size']}")
        # Use the site's cart and checkout functions, not direct privileged database writes.
        js(page,"cart.length=0; updateCartUI()")
        js(page,"""c=>{cart.push({prodId:c.id,name:c.name,price:c.price,color:c.color,size:c.size,qty:1,img:'',isPreorder:false});updateCartUI();} """.replace(' "','"') if False else """(c)=>{cart.push({prodId:c.id,name:c.name,price:c.price,color:c.color,size:c.size,qty:1,img:'',isPreorder:false});updateCartUI();}""" ) if False else None
        page.evaluate("""(c)=>{cart.push({prodId:c.id,name:c.name,price:c.price,color:c.color,size:c.size,qty:1,img:'',isPreorder:false});updateCartUI();}""",candidate)
        record('購物車金額','PASS' if js(page,'cart.reduce((s,i)=>s+i.price*i.qty,0)')==candidate['price'] else 'FAIL')
        js(page,'openCheckoutModal()')
        page.locator('#checkoutModal').wait_for(state='visible',timeout=10000)
        if page.locator('#mergeExistingOrderChk').count():page.locator('#mergeExistingOrderChk').uncheck(force=True)
        page.locator('#confirmOrderPolicyChk').check(force=True)
        # Exactly one submit; no automatic retries.
        page.locator('#btnSubmitCustomerOrder').click(timeout=10000)
        page.wait_for_timeout(7000)
        after=db(page,'orders','id,user_id,status,created_at',user_id=identity)
        old_ids={o['id'] for o in before}
        new=[o for o in after if o['id'] not in old_ids]
        if len(new)!=1:
          record('建立測試訂單','FAIL',f'預期新增1筆，實際可見新增{len(new)}筆；不會重試送單')
          return
        order_id=new[0]['id']
        Path('s31_test_order_id.txt').write_text(order_id,encoding='utf-8')
        record('建立測試訂單','PASS','已產生一筆新訂單（完整ID另存 artifact）')
        items=db(page,'order_items','order_id,variant_id,quantity,unit_price',order_id=order_id)
        ok=len(items)==1 and str(items[0]['variant_id'])==str(candidate['variant_id']) and int(items[0]['quantity'])==1
        record('訂單商品與規格寫入','PASS' if ok else 'FAIL',f'商品筆數={len(items)}')
        page.reload(wait_until='domcontentloaded')
        page.wait_for_timeout(4000)
        page.wait_for_function("typeof s31SupabaseUser!=='undefined' && !!s31SupabaseUser",timeout=25000)
        persisted=db(page,'orders','id,user_id,status',id=order_id)
        record('重新整理後訂單仍存在','PASS' if len(persisted)==1 else 'FAIL')
        record('管理採買／結單／收款／退款／物流','BLOCKED','尚未加入安全的專用測試資料操作及可核對的回復機制，避免改動真實訂單')
      except Exception as e:
        record('測試執行','FAIL',str(e).split('Call log:')[0][:300])
      finally:
        record('JavaScript 未捕獲錯誤','PASS' if not errors else 'FAIL',' | '.join(errors[:2])[:250])
        browser.close()

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--url',default='https://ssss31.netlify.app/')
    ap.add_argument('--allow-order',action='store_true')
    ap.add_argument('--browser',action='store_true')
    args=ap.parse_args()
    try:test(args.url,args.allow_order)
    finally:
      summary={x:sum(r['status']==x for r in results) for x in ['PASS','FAIL','BLOCKED','WARNING']}
      Path('s31_qa_report.json').write_text(json.dumps({'time':datetime.datetime.now(datetime.timezone.utc).isoformat(),'results':results,'summary':summary},ensure_ascii=False,indent=2),encoding='utf-8')
      print('結果:',summary)
    return 1 if summary['FAIL'] else 0
if __name__=='__main__':sys.exit(main())
