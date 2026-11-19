"""Post-inference mode comparison, no reference coordinates."""
import hashlib
from shapely.geometry import shape


def compare_region_orders(e,f):
    def key(r):return r.hypothesis_id+':'+hashlib.sha256(shape(r.geometry).normalize().wkb).hexdigest()
    old={key(r):(i,r) for i,r in enumerate(e.regions,1)};new={key(r):(i,r) for i,r in enumerate(f.regions,1)}
    rows=[dict(mode=k,E_rank=old[k][0] if k in old else None,F_rank=new[k][0] if k in new else None,
       automatic_relation_score=new[k][1].automatic_relation_score if k in new else None) for k in sorted(set(old)|set(new))]
    return dict(regions=rows,common_modes=len(set(old)&set(new)),changed_common_ranks=sum(old[k][0]!=new[k][0] for k in set(old)&set(new)),
      new_modes=len(set(new)-set(old)),dropped_modes=len(set(old)-set(new)))
