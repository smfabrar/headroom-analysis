//! Diagnostic: what does the LIVE scorer actually rank for a scalar array?
//! Compares HybridScorer (the crusher default) against BM25Scorer.
use headroom_core::relevance::{BM25Scorer, HybridScorer, RelevanceScorer};

fn rank_of(scores: &[f64], target: usize) -> usize {
    let mut idx: Vec<usize> = (0..scores.len()).collect();
    idx.sort_by(|&a, &b| scores[b].partial_cmp(&scores[a]).unwrap().then(a.cmp(&b)));
    idx.iter().position(|&i| i == target).unwrap() + 1
}

#[test]
fn probe_scalar_ranking() {
    let items: Vec<String> = (1..=200).map(|i| format!("INV-2026-{:04}", i)).collect();
    let refs: Vec<&str> = items.iter().map(|s| s.as_str()).collect();
    let target = 43; // INV-2026-0044
    let query = "Is INV-2026-0044 in the list? Report its status.";

    let hybrid = HybridScorer::default();
    let bm25 = BM25Scorer::default();

    let hs: Vec<f64> = hybrid.score_batch(&refs, query).iter().map(|s| s.score).collect();
    let bs: Vec<f64> = bm25.score_batch(&refs, query).iter().map(|s| s.score).collect();

    let hmax = hs.iter().cloned().fold(0.0_f64, f64::max);
    let bmax = bs.iter().cloned().fold(0.0_f64, f64::max);

    println!("\n=== SCORER PROBE (target index {}, {}) ===", target, items[target]);
    println!("embedding available : {}", HybridScorer::default().is_available());
    println!("HYBRID  target_score={:.4}  max={:.4}  rank={}  above_0.3={}",
             hs[target], hmax, rank_of(&hs, target), hs.iter().filter(|&&x| x >= 0.3).count());
    println!("BM25    target_score={:.4}  max={:.4}  rank={}  above_0.3={}",
             bs[target], bmax, rank_of(&bs, target), bs.iter().filter(|&&x| x >= 0.3).count());
    println!("HYBRID top-5: {:?}", {
        let mut i: Vec<usize> = (0..hs.len()).collect();
        i.sort_by(|&a,&b| hs[b].partial_cmp(&hs[a]).unwrap());
        i[..5].iter().map(|&j| (items[j].clone(), (hs[j]*1000.0).round()/1000.0)).collect::<Vec<_>>()
    });
    println!("BM25   top-5: {:?}", {
        let mut i: Vec<usize> = (0..bs.len()).collect();
        i.sort_by(|&a,&b| bs[b].partial_cmp(&bs[a]).unwrap());
        i[..5].iter().map(|&j| (items[j].clone(), (bs[j]*1000.0).round()/1000.0)).collect::<Vec<_>>()
    });
}
