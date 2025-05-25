import os
import json
import tqdm
import shutil
import argparse
import multiprocessing
from functools import partial
from datasets import load_dataset
from demo.infer import LiveCCDemoInfer
from utils.multiprocessor import local_mp

def parse_args():
    parser = argparse.ArgumentParser(
        description="Distributed LiveCC generation over the LiveSports-3K CC split"
    )
    parser.add_argument(
        "--model_name_or_path", type=str, required=True,
        help="HuggingFace model path, e.g., chenjoya/LiveCC-7B-Instruct"
    )
    parser.add_argument(
        "--not_instruct_model", action="store_true", dest="not_instruct_model", help="Disable instruct model mode"
    )
    parser.add_argument(
        "--num_workers", type=int, default=8,
        help="Number of parallel processes/gpus to use"
    )
    parser.add_argument(
        "--repetition_penalty", type=float, default=1.15,
        help="Repetition penalty for generation. When performing livecc, 1.15 can remove most repetition."
    )
    parser.add_argument(
        "--output_dir", type=str,
        default="evaluation/livesports3kcc/livecc",
        help="Directory to write generated JSON outputs"
    )
    return parser.parse_args()

def livecc_worker(
    device_id: int,
    model_name_or_path: str,
    save_dir: str,
    simple_ctx: bool,
    repetition_penalty: float,
    num_workers: int
):
    infer = LiveCCDemoInfer(model_path=model_name_or_path, device=f'cuda:{device_id}')

    ds = load_dataset('stdKonjac/LiveSports-3K', name='LiveSports_3K_CC', split="test")
    idxs = list(range(len(ds)))
    idxs_on_device = idxs[device_id::num_workers]

    # Prepare temporary save folder for this model
    os.makedirs(save_dir, exist_ok=True)

    for idx in tqdm.tqdm(idxs_on_device, desc=f"Device {device_id}", total=len(idxs_on_device)):
        save_path = os.path.join(save_dir, f"{idx}.json")
        if os.path.exists(save_path):
            continue

        record = ds[idx]
        video = record.get("video")
        video_id = record.get("video_id")
        event_id = record.get("event_id")
        video_start = record.get("begin")
        video_end = record.get("end")
        title = record.get("event_title")
        preasr = record.get("preasr_text")

        if simple_ctx:
            title = '' if preasr else title # title or preasr
            overall_prompt = f'{title}\n{preasr}'.strip()
        else:
            commentary_prompt = (
                "You are an expert video commentator providing real-time, insightful, "
                "and engaging commentary on visual content.\n"
            )
            overall_prompt = commentary_prompt
            if title:
                overall_prompt += f"This is a video titled \"{title}\".\n"
            if preasr:
                overall_prompt += f"Here is previous commentary of the video:\n\n{preasr}\n\n"
                overall_prompt += "Please continue to comment the video."

        responses = infer.live_cc_once_for_evaluation(
            query=overall_prompt,
            video=video, video_start=video_start, video_end=video_end,
            max_new_tokens=32,
            repetition_penalty=repetition_penalty,
        )

        overall_cc = (
            ' '.join(cc.replace(' ...', '') for _, _, cc in responses if cc)
            .strip() + '...'
        )

        with open(save_path, 'w') as wf:
            json.dump({
                "video_id": video_id,
                'event_id': event_id,
                "begin": video_start,
                "end": video_end,
                "pred": overall_cc
            }, wf)

if __name__ == "__main__":
    args = parse_args()
    multiprocessing.set_start_method('spawn', force=True)
    save_dir = os.path.join(args.output_dir, os.path.basename(args.model_name_or_path))
    worker_fn = partial(
        livecc_worker,
        model_name_or_path=args.model_name_or_path,
        save_dir=save_dir,
        simple_ctx=args.not_instruct_model,
        repetition_penalty=args.repetition_penalty,
        num_workers=args.num_workers,
    )
    local_mp(
        list(range(args.num_workers)),
        worker_fn,
        desc="livecc_generation",
        num_workers=args.num_workers
    )
    # jsons -> jsonl
    save_path = save_dir + '.jsonl'
    with open(save_path, 'w') as wf:
        for file in os.listdir(save_dir):
            datum = json.load(open(os.path.join(save_dir, file))) 
            wf.write(json.dumps(datum) + '\n')
    # remove save_dir
    shutil.rmtree(save_dir)

