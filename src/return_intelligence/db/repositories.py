from __future__ import annotations
import json, sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from .connection import connect, transaction
from .migrations import apply_migrations
from ..domain.errors import ConflictError, NotFoundError


def now() -> str: return datetime.now(timezone.utc).isoformat()
def canonical(value: Any) -> str: return json.dumps(value,sort_keys=True,separators=(",",":"),default=str)
def rowdict(row): return dict(row) if row else None

class Repository:
    def __init__(self, db_path: Path | str): self.db_path=Path(db_path)
    def initialize(self):
        self.db_path.parent.mkdir(parents=True,exist_ok=True)
        script=Path(__file__).with_name("schema.sql").read_text()
        conn=connect(self.db_path)
        try:
            conn.executescript(script)
            apply_migrations(conn)
            conn.commit()
        finally: conn.close()
    def get_setting(self,key,default=None):
        row=self.one("SELECT setting_value FROM demo_settings WHERE setting_key=?",(key,))
        return row["setting_value"] if row else default
    def set_setting(self,key,value,updated_by):
        with transaction(self.db_path,True) as c:
            c.execute("INSERT INTO demo_settings(setting_key,setting_value,updated_by,updated_at) VALUES(?,?,?,?) ON CONFLICT(setting_key) DO UPDATE SET setting_value=excluded.setting_value,updated_by=excluded.updated_by,updated_at=excluded.updated_at",(key,str(value),updated_by,now()))
    def one(self,sql,args=()):
        with transaction(self.db_path) as conn: return rowdict(conn.execute(sql,args).fetchone())
    def all(self,sql,args=()):
        with transaction(self.db_path) as conn: return [dict(r) for r in conn.execute(sql,args)]
    def get_order_item(self,order_id,order_item_id=None):
        sql="""SELECT oi.*,o.customer_zone,o.fulfillment_status,p.model_id,p.name,p.season_profile,p.similar_group FROM order_items oi JOIN orders o USING(order_id) JOIN products p USING(sku) WHERE o.order_id=? AND o.synthetic=1"""
        args=[order_id]
        if order_item_id: sql+=" AND oi.order_item_id=?"; args.append(order_item_id)
        rows=self.all(sql,args)
        if not rows: raise NotFoundError("synthetic order/item not found")
        return rows[0]
    def create_return(self,return_id,order_item_id):
        stamp=now()
        with transaction(self.db_path,True) as c:
            c.execute("INSERT INTO return_requests(return_id,order_item_id,state,created_at,updated_at) VALUES(?,?,'DRAFT',?,?)",(return_id,order_item_id,stamp,stamp))
        return self.get_return(return_id)
    def get_return(self,return_id):
        row=self.one("""SELECT r.*,oi.order_id,oi.sku,oi.size,oi.color,oi.batch_id,oi.is_returnable,oi.delivered,o.customer_zone,p.model_id,p.name,p.season_profile FROM return_requests r JOIN order_items oi USING(order_item_id) JOIN orders o USING(order_id) JOIN products p USING(sku) WHERE return_id=?""",(return_id,))
        if not row: raise NotFoundError("return request not found")
        return row
    def update_return(self,c,return_id,expected_version,**fields):
        fields["updated_at"]=now(); fields["version"]=expected_version+1
        assignments=",".join(f"{k}=?" for k in fields)
        values=list(fields.values())+[return_id,expected_version]
        cur=c.execute(f"UPDATE return_requests SET {assignments} WHERE return_id=? AND version=?",values)
        if cur.rowcount!=1: raise ConflictError("request changed; reload and retry")
    def activity(self,c,return_id,agent,action,rationale,input_data,output_data):
        c.execute("INSERT INTO activity_log(return_id,agent_name,action,rationale,input_json,output_json,created_at) VALUES(?,?,?,?,?,?,?)",(return_id,agent,action,rationale,canonical(input_data),canonical(output_data),now()))
    def inventory_options(self,sku,size=None,color=None):
        sql="""SELECT i.*, (on_hand-reserved) available FROM inventory i JOIN products p USING(sku) JOIN destinations d USING(destination_id) WHERE p.active=1 AND d.active=1 AND d.operational_status='OPEN' AND on_hand-reserved>0 AND i.sku=?"""; args=[sku]
        if size is not None: sql+=" AND i.size=?";args.append(size)
        if color is not None: sql+=" AND i.color=?";args.append(color)
        return self.all(sql,args)
    def similar_inventory(self,similar_group):
        return self.all("""SELECT i.*,(on_hand-reserved) available FROM inventory i JOIN products p USING(sku) JOIN destinations d USING(destination_id) WHERE p.similar_group=? AND on_hand-reserved>0 AND p.active=1 AND d.active=1 AND d.operational_status='OPEN'""",(similar_group,))
    def customer_messages(self,return_id): return self.all("SELECT * FROM customer_messages WHERE return_id=? ORDER BY sent_at,message_id",(return_id,))
    def destinations(self,destination_type,zone,dropoff=False):
        sql="""SELECT d.*,dd.distance_km FROM destinations d JOIN destination_distances dd USING(destination_id) WHERE d.destination_type=? AND d.active=1 AND d.operational_status='OPEN' AND d.current_load_units<d.capacity_units AND dd.customer_zone=?""";args=[destination_type,zone]
        if dropoff: sql+=" AND d.dropoff_eligible=1"
        return self.all(sql,args)
    def destination(self,destination_id): return self.one("SELECT * FROM destinations WHERE destination_id=?",(destination_id,))
    def active_destinations(self,types):
        types=tuple(types)
        return self.all(f"SELECT * FROM destinations WHERE active=1 AND operational_status='OPEN' AND destination_type IN({','.join('?'*len(types))}) ORDER BY destination_type,destination_id",types)
    def latest_destination_decision(self,return_id):
        return self.one("""SELECT s.*,d.name chosen_destination_name FROM staff_destination_decisions s JOIN destinations d ON d.destination_id=s.chosen_destination_id WHERE s.return_id=? ORDER BY s.decided_at DESC,s.rowid DESC LIMIT 1""",(return_id,))
    def open_review(self,return_id): return self.one("SELECT * FROM review_queue WHERE return_id=? AND status='OPEN'",(return_id,))
    def route(self,return_id): return self.one("SELECT * FROM routes WHERE return_id=?",(return_id,))
    def activities(self,return_id): return self.all("SELECT * FROM activity_log WHERE return_id=? ORDER BY activity_id",(return_id,))
    def alert(self,alert_id): return self.one("SELECT * FROM early_warning_alerts WHERE alert_id=?",(alert_id,))
    def alert_status_history(self,alert_id): return self.all("SELECT * FROM alert_status_events WHERE alert_id=? ORDER BY changed_at,rowid",(alert_id,))
    def flagged_series(self):
        """Product/series flags derived from active (OPEN/INVESTIGATING) alerts; never stored, so they follow alert status."""
        flags={}
        for alert in self.all("SELECT * FROM early_warning_alerts WHERE status IN('OPEN','INVESTIGATING') ORDER BY created_at,alert_id"):
            try: evidence=json.loads(alert["evidence_json"] or "{}")
            except (TypeError,ValueError): evidence={}
            dimension=alert["dimension_value"] or ""
            model=evidence.get("model_id") if isinstance(evidence,dict) else None
            if not model and alert["dimension_type"] in ("MODEL","MODEL_SIZE"): model=dimension.split("|")[0]  # MODEL_SIZE = legacy v1 alert
            if not model:
                sku=(evidence.get("sku") if isinstance(evidence,dict) else None) or (dimension.split("|")[0] if alert["dimension_type"]=="SKU_SIZE" else None)
                product=self.one("SELECT model_id FROM products WHERE sku=?",(sku,)) if sku else None
                model=product["model_id"] if product else None
            if not model: continue
            flag=flags.get(model)
            if flag is None:
                names=[r["name"] for r in self.all("SELECT DISTINCT name FROM products WHERE model_id=? ORDER BY name",(model,))]
                flag=flags[model]={"model_id":model,"product_names":names,"alert_ids":[],"levels":[],"categories":[],"statuses":[]}
            flag["alert_ids"].append(alert["alert_id"])
            for key,value in (("levels",alert["dimension_type"]),("categories",alert["category"]),("statuses",alert["status"])):
                if value not in flag[key]: flag[key].append(value)
        return [flags[key] for key in sorted(flags)]
    def kpis(self):
        from ..services.kpis import compute_kpis  # lazy: services imports the agents, which import this module
        decisions={r["d"]:r["n"] for r in self.all("SELECT current_decision d,count(*) n FROM return_requests WHERE current_decision IS NOT NULL GROUP BY current_decision")}
        modes={r["m"]:r["n"] for r in self.all("SELECT COALESCE(fulfillment_mode,'UNKNOWN') m,count(*) n FROM routes GROUP BY m")}
        return compute_kpis(decisions,modes)
    def dashboard(self):
        return {"requests":self.all("SELECT return_id,state,current_decision,final_grade,updated_at FROM return_requests ORDER BY updated_at DESC"),"open_reviews":self.all("SELECT * FROM review_queue WHERE status='OPEN'"),"alerts":self.all("SELECT * FROM early_warning_alerts ORDER BY created_at DESC"),"artifacts":self.all("SELECT * FROM fulfillment_artifacts ORDER BY created_at DESC"),"kpis":self.kpis(),"flags":self.flagged_series()}
