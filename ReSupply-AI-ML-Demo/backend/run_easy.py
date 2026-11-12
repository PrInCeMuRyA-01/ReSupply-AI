"""Launch this separate local shop without taking the old app's port 8000."""
from pathlib import Path
import os
import socket
import threading
import webbrowser
import argparse


def main():
    parser=argparse.ArgumentParser(description='Start the empty shop or the prepared ML demo.')
    parser.add_argument('--ml-demo',action='store_true',help='Prepare 90 synthetic days per sample product, train real models, then open /demo/.')
    args=parser.parse_args()
    os.chdir(Path(__file__).resolve().parent)
    if args.ml_demo:
        print('Preparing 90 recent synthetic days per product and training actual ML models. Please wait...',flush=True)
        import main as code
        from prepare_ml_demo import prepare_ml_demo
        result=prepare_ml_demo(code)
        for product in result['products']:
            print(product['name']+': '+str(product['training_days'])+' days; '+str(product['selected_method'])+'; ML MAE='+str(product['model_mae'])+', mean MAE='+str(product['baseline_mae']),flush=True)
        print(result['message'],flush=True)
    port=None
    for candidate in range(8001,8012):
        with socket.socket() as probe:
            try:probe.bind(('127.0.0.1',candidate))
            except OSError:continue
            port=candidate;break
    if port is None:raise SystemExit('Ports 8001-8011 are busy. Close a previous Easy Start terminal and retry.')
    base=f'http://127.0.0.1:{port}'
    url=base+('/demo/' if args.ml_demo else '')
    database_name='resupply-ml-demo.db' if args.ml_demo else 'resupply-easy.db'
    print('\nReSupply AI - ML Demo Ready\nOpen: '+url+'\nDatabase: '+database_name+'\nKeep this terminal open. Ctrl+C stops the app.\n',flush=True)
    timer=threading.Timer(2,lambda:webbrowser.open(url));timer.daemon=True;timer.start()
    import uvicorn
    uvicorn.run('main:app',host='127.0.0.1',port=port,log_level='info')


if __name__=='__main__':main()
