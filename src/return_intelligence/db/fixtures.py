"""Stable, invented fixtures. Every identifier and record is synthetic."""
PRODUCTS=[
('SYN-RUNNER-100','SYN-MODEL-RUNNER','Everyday Runner','YEAR_ROUND','RUNNER',1),
('SYN-SANDAL-200','SYN-MODEL-SANDAL','Summer Sandal','SUMMER','CASUAL',1),
('SYN-BOOT-300','SYN-MODEL-BOOT','Winter Boot','WINTER','BOOT',1),
('SYN-RUNNER-110','SYN-MODEL-RUNNER-ALT','Comfort Runner','YEAR_ROUND','RUNNER',1)]
ORDERS=[
('SYN-O-SIZE-001','SYN-RUNNER-100','8','Blue',1,1),('SYN-O-UNCLEAR-001','SYN-RUNNER-100','8','Blue',1,1),
('SYN-O-A95-001','SYN-RUNNER-100','8','Blue',1,1),('SYN-O-LOW75-001','SYN-RUNNER-100','8','Blue',1,1),
('SYN-O-B-001','SYN-RUNNER-100','8','Blue',1,1),('SYN-O-C-001','SYN-RUNNER-100','8','Blue',1,1),
('SYN-O-SANDAL-001','SYN-SANDAL-200','7','Tan',1,1),('SYN-O-WORN-001','SYN-RUNNER-100','8','Blue',1,1),
('SYN-O-DEFECT-001','SYN-BOOT-300','9','Black',1,1),('SYN-O-DELAY-001','SYN-BOOT-300','9','Black',1,1),
('SYN-O-MISSING-001','SYN-RUNNER-110','8','White',1,0),('SYN-O-COLOR-001','SYN-RUNNER-100','8','Blue',1,1),
# Appended at the END only: order_item ids (SYN-OI-NNN) are positional.
('SYN-O-OOS-001','SYN-RUNNER-100','8','Blue',1,0)]
SCENARIOS={
"size_exchange":{"order_id":"SYN-O-SIZE-001","reason":"The shoes are too small","fixture":"eligible_a_95"},
"unclear":{"order_id":"SYN-O-UNCLEAR-001","reason":"I dislike the fit","fixture":"unclear"},
"eligible_a_95":{"order_id":"SYN-O-A95-001","reason":"Wrong color","fixture":"eligible_a_95"},
"eligible_75":{"order_id":"SYN-O-LOW75-001","reason":"I dislike them","fixture":"eligible_75"},
"grade_b":{"order_id":"SYN-O-B-001","reason":"I prefer another style","fixture":"eligible_75"},
"grade_c":{"order_id":"SYN-O-C-001","reason":"I prefer another style","fixture":"eligible_75"},
"seasonal_sandal":{"order_id":"SYN-O-SANDAL-001","reason":"Wrong color","fixture":"eligible_a_95"},
"worn":{"order_id":"SYN-O-WORN-001","reason":"I wore these outside","fixture":"worn_ineligible"},
"defect":{"order_id":"SYN-O-DEFECT-001","reason":"The sole is separating, quality issue","fixture":"suspected_defect"},
"delayed":{"order_id":"SYN-O-DELAY-001","reason":"Shipping is delayed","fixture":None},
"missing":{"order_id":"SYN-O-MISSING-001","reason":"My item never arrived and is missing","fixture":None},
"out_of_stock":{"order_id":"SYN-O-OOS-001","reason":"The shoes were out of stock and never shipped","fixture":None},
"matrix":{"description":"all eight pure routing combinations are asserted in tests"}}
