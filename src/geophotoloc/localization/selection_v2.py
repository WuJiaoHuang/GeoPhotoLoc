"""Bounded, evidence-first mode retention. No references or geographic identities."""
import hashlib
from math import hypot
from shapely import STRtree
from shapely.ops import unary_union


def evidence_quality(score):
    # Six decimal bins are a numerical near-tie convention, not calibrated utility.
    return (round(score.score,6),round(score.components.get('geometry',0.),6),
            score.reliable_landmark_count)


def _mode(geometry,members,scores,origins=None):
    members=sorted(set(members))
    best=min(members,key=lambda p:(-scores[p].score,p))
    identifier=hashlib.sha256(geometry.normalize().wkb+repr(members).encode()).hexdigest()[:20]
    # Use an existing high-score sample, stable to sub-mm geometry transport.
    anchor=min(members,key=lambda p:(-round(scores[p].score,6),round(p[0],3),round(p[1],3),p))
    center=(round(anchor[0],3),round(anchor[1],3))
    return dict(geometry=geometry,members=members,best=best,id=identifier,
                origins=origins or [identifier],quality=evidence_quality(scores[best]),center=center,stable_key=(*center,*(round(v,3) for v in geometry.bounds)))


def select_quality_modes(entries,scores,limit,max_merge_area_m2):
    if limit<1 or max_merge_area_m2<=0:raise ValueError('Positive output and merge budgets required')
    modes=sorted((_mode(g,m,scores) for g,m in entries if m and not g.is_empty),key=lambda m:(m['stable_key'],m['id']))
    original_count=len(modes)
    # Exact connected unions only, bounded by the old single-tile area. No hull/buffer.
    tree=STRtree([m['geometry'] for m in modes]);parents=list(range(len(modes)))
    def root(i):
        while parents[i]!=i:
            parents[i]=parents[parents[i]];i=parents[i]
        return i
    for i,item in enumerate(list(modes)):
        for j in sorted(map(int,tree.query(item['geometry'],predicate='intersects'))):
            if j<=i:continue
            a,b=root(i),root(j)
            if a==b or modes[a]['quality']!=modes[b]['quality']:continue
            union=modes[a]['geometry'].union(modes[b]['geometry'])
            if union.geom_type!='Polygon' or union.area>max_merge_area_m2+1e-6:continue
            modes[a]=_mode(union,modes[a]['members']+modes[b]['members'],scores,modes[a]['origins']+modes[b]['origins'])
            parents[b]=a
    modes=[m for i,m in enumerate(modes) if root(i)==i]
    remaining=list(modes);chosen=[];decisions=[]
    while remaining:
        best_quality=max(m['quality'] for m in remaining)
        cohort=[m for m in remaining if m['quality']==best_quality]
        def diversity(m):
            return min((hypot(m['center'][0]-s['center'][0],m['center'][1]-s['center'][1]) for s in chosen),default=0.)
        candidate=min(cohort,key=lambda m:(-round(diversity(m),3),m['stable_key'],m['id']))
        remaining.remove(candidate)
        covered=any(m['geometry'].covers(candidate['geometry']) for m in chosen)
        keep=not covered and len(chosen)<limit
        reason='quality_tier_then_diversity' if keep else 'covered_by_retained_mode' if covered else 'output_budget_tied_quality' if chosen and candidate['quality']==chosen[-1]['quality'] else 'output_budget_lower_quality'
        decision=dict(mode_id=candidate['id'],source_mode_ids=sorted(candidate['origins']),retained=keep,reason=reason,
          quality=list(candidate['quality']),score=scores[candidate['best']].score,best_xy=list(candidate['best']),
          bounds_xy=list(candidate['geometry'].bounds),area_m2=candidate['geometry'].area,member_count=len(candidate['members']),
          diversity_distance_m=diversity(candidate),geometry_sha256=hashlib.sha256(candidate['geometry'].normalize().wkb).hexdigest())
        decisions.append(decision)
        if keep:chosen.append(candidate)
    top=max((m['quality'] for m in modes),default=None)
    top_count=sum(m['quality']==top for m in modes)
    audit=dict(strategy='quality_v2-coordinate-stable',original_modes=original_count,merged_modes=len(modes),output_modes=len(chosen),output_limit=limit,
       merge_area_limit_m2=max_merge_area_m2,ambiguous=top_count>1,top_quality_modes=top_count,
       omitted_top_quality_modes=sum(not d['retained'] and tuple(d['quality'])==top and d['reason']!='covered_by_retained_mode' for d in decisions),
       decisions=decisions,coordinate_system='same local east/north metre CRS as sample_trace',
       tradeoff='Compact exact unions and bounded output cannot guarantee retention of every tied spatial mode; omitted evidence remains in decisions.')
    return [(m['geometry'],m['members']) for m in chosen],audit
