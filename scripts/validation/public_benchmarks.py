#!/usr/bin/env python3
"""Reproducible local evaluation: BEIR SciFact test and FUNSD test OCR.

Download datasets from their publishers separately. Never fit or tune on test labels.
No dataset contents are written to the results file.
"""
import sys
sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[2]))

import argparse
import asyncio
from collections import Counter
import hashlib
import json
import math
from pathlib import Path
import re
import time
import unicodedata


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def edit_distance(a, b):
    row = list(range(len(b) + 1))
    for i, x in enumerate(a, 1):
        new = [i]
        for j, y in enumerate(b, 1):
            new.append(min(new[-1] + 1, row[j] + 1, row[j - 1] + (x != y)))
        row = new
    return row[-1]


def words(text):
    return re.findall(r'\w+', unicodedata.normalize('NFKC', text).lower())


async def retrieval(root, output):
    import numpy as np
    from src.services.embedding.client import get_embedding_client
    from src.services.embedding.config import get_embedding_config
    corpus = [json.loads(line) for line in (root / 'corpus.jsonl').read_text().splitlines()]
    queries = {r['_id']: r['text'] for r in map(json.loads, (root / 'queries.jsonl').read_text().splitlines())}
    qrels = {}
    for line in (root / 'qrels/test.tsv').read_text().splitlines()[1:]:
        q, d, score = line.split('\t')
        if int(score) > 0: qrels.setdefault(q, {})[d] = int(score)
    config = get_embedding_config()
    client = get_embedding_client()
    started = time.monotonic()
    vectors = np.asarray(await client.embed([r['title']+'\n'+r['text'] for r in corpus], input_type='passage'), dtype=np.float32)
    query_ids = sorted(qrels)
    qvectors = np.asarray(await client.embed([queries[q] for q in query_ids], input_type='query'), dtype=np.float32)
    vectors /= np.maximum(np.linalg.norm(vectors, axis=1, keepdims=True), 1e-12)
    qvectors /= np.maximum(np.linalg.norm(qvectors, axis=1, keepdims=True), 1e-12)
    ids = [r['_id'] for r in corpus]
    totals = Counter()
    for qid, scores in zip(query_ids, qvectors @ vectors.T):
        ranking = [ids[i] for i in np.argsort(-scores)[:10]]
        rel = qrels[qid]
        for k in (1, 5, 10): totals[f'recall@{k}'] += sum(d in rel for d in ranking[:k]) / len(rel)
        totals['mrr@10'] += next((1 / (i+1) for i,d in enumerate(ranking) if d in rel), 0)
        dcg = sum((2**rel.get(d,0)-1) / math.log2(i+2) for i,d in enumerate(ranking))
        ideal = sum((2**r-1) / math.log2(i+2) for i,r in enumerate(sorted(rel.values(),reverse=True)[:10]))
        totals['ndcg@10'] += dcg / ideal if ideal else 0
    result = {'benchmark':'BEIR/SciFact','split':'test','queries':len(query_ids),'corpus':len(corpus),
              'model':config.model,'dimensions':config.dim,'max_tokens':config.max_tokens,
              'metrics':{k:v/len(query_ids) for k,v in totals.items()},'elapsed_seconds':time.monotonic()-started,
              'input_sha256':{str(p.relative_to(root)):sha(p) for p in [root/'corpus.jsonl',root/'queries.jsonl',root/'qrels/test.tsv']},
              'scope':'Dense retrieval through the production embedding client; not an end-to-end generation/citation score.'}
    output.write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result),flush=True)


async def ocr(root, output, parser, count):
    import tempfile
    from src.services.document_processing import parse_document, DocumentProcessingConfig
    annotations = sorted((root/'testing_data/annotations').glob('*.json'))[:count]
    if len(annotations) != count: raise ValueError('Missing FUNSD test annotations')
    results=[]
    with tempfile.TemporaryDirectory() as directory:
        for annotation in annotations:
            data=json.loads(annotation.read_text())
            truth=' '.join(item['text'] for item in data['form'] if item.get('text'))
            image=root/'testing_data/images'/f'{annotation.stem}.png'
            started=time.monotonic()
            try:
                parsed=await parse_document(image,Path(directory)/annotation.stem,
                    DocumentProcessingConfig(parser=parser,mineru_tier='basic',timeout_seconds=300))
                predicted=' '.join(str(b.get('text','')) for b in parsed['content_list'])
                ref,hyp=words(truth),words(predicted)
                common=sum((Counter(ref)&Counter(hyp)).values())
                precision=common/max(len(hyp),1);recall=common/max(len(ref),1)
                results.append({'id':annotation.stem,'cer':edit_distance(' '.join(ref),' '.join(hyp))/max(len(' '.join(ref)),1),
                                'wer':edit_distance(ref,hyp)/max(len(ref),1), 'token_precision':precision,'token_recall':recall,
                                'token_f1':2*precision*recall/max(precision+recall,1e-12),
                                'seconds':time.monotonic()-started,'image_sha256':sha(image),'annotation_sha256':sha(annotation)})
            except Exception as error:
                results.append({'id':annotation.stem,'error':str(error),'seconds':time.monotonic()-started})
            print(json.dumps(results[-1]),flush=True)
    successful=[r for r in results if 'error' not in r]
    result={'benchmark':'FUNSD','split':'test','selection':'first sorted official test IDs','parser':parser,'mineru_tier':'basic',
            'requested':count,'successful':len(successful),'results':results,
            'macro_metrics':({key:sum(r[key] for r in successful)/len(successful) for key in ('cer','wer','token_precision','token_recall','token_f1','seconds')} if successful else None),
            'scope':'English noisy forms. Entity annotation order differs from page reading order; report order-sensitive CER/WER and unordered token scores separately.'}
    output.write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result['macro_metrics']),flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('benchmark',choices=['retrieval','ocr']);p.add_argument('--dataset',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True);p.add_argument('--parser',default='mineru');p.add_argument('--count',type=int,default=10)
    args=p.parse_args();args.output.parent.mkdir(parents=True,exist_ok=True)
    asyncio.run(retrieval(args.dataset,args.output) if args.benchmark=='retrieval' else ocr(args.dataset,args.output,args.parser,args.count))
