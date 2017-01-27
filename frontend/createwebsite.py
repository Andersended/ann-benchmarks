import argparse
import os, json, pickle
import numpy
from collections import deque

colors = deque(["rgba(151,187,205,1)", "rgba(220,220,220,1)", "rgba(247,70,74,1)", "rgba(70,191,189,1)",
          "rgba(253,180,92,1)", "rgba(148,159,177,1)", "rgba(77,83,96,1)"])

metrics = {
    "k-nn": {
        "description": "10-NN precision - larger is better",
        "initial-y": float("-inf"),
        "plot": lambda y, last_y: y > last_y,
        "xlim": [0.0, 1.03]
    },
    "epsilon": {
        "description": "(epsilon)",
        "initial-y": float("-inf"),
        "plot": lambda y, last_y: y > last_y
    },
    "rel": {
        "description": "(rel)",
        "initial-y": float("inf"),
        "plot": lambda y, last_y: y < last_y
    }
}

parser = argparse.ArgumentParser()
parser.add_argument(
    '--dataset',
    nargs = '*')
parser.add_argument(
    '--precision',
    help = 'Which precision metric to use',
    nargs = '*'
    #choices = list(metrics.keys()),
    #default = 'k-nn',
    )
parser.add_argument(
    '--outputdir',
    help = 'Select output directory',
    action = 'store'
    )
args = parser.parse_args()

outputdir = ""

if args.outputdir != None:
    outputdir = args.outputdir


# XXX: this is copied-and-pasted from main.py
def get_fn(base, dataset, limit = -1):
    fn = os.path.join(base, dataset)

    if limit != -1:
        fn += '-%d' % limit
    if os.path.exists(fn + '.gz'):
        fn += '.gz'
    else:
        fn += '.txt'

    d = os.path.dirname(fn)
    if not os.path.exists(d):
        os.makedirs(d)

    return fn

def create_plot(ds, all_data, metric):
    output_str = """
        <h2>%(id)s with %(metric)s</h2>
        <canvas id="chart%(metric)s" width="800" height="600"></canvas>
        <script>
            var ctx = document.getElementById("chart%(metric)s");
            var chart = new Chart(ctx, {
                type: "line",
                data: { datasets: [""" % { "id" : ds, "metric" :  metric["description"] }
    for algo in sorted(all_data.keys(), key=lambda x: x.lower()):
            data = all_data[algo]
            data.sort(key=lambda t: t[-2]) # sort by time
            ys = [1.0 / t[-2] for t in data] # queries per second
            xs = [t[-1] for t in data]
            ls = [t[0] for t in data]

            # Plot Pareto frontier
            xs, ys = [], []
            last_y = metric["initial-y"]
            for t in data:
                y = t[-1]
                if metric["plot"](y, last_y):
                    last_y = y
                    xs.append(t[-1])
                    ys.append(1.0 / t[-2])
            output_str += """
                {
                    label: "%(algo)s ",
                    fill: false,
                    borderColor: "%(color)s",
                    data: [ """ % {"algo" : algo, "color" : colors[0] }

            for i in range(len(xs)):
                output_str += """
                        { x: %(x)s, y: %(y)s },""" % {"x" : str(xs[i]), "y" : str(ys[i]) }
            output_str += """
                ]},"""
            colors.rotate(1)

    output_str += """
            ]}, options: {
                        responsive: false,
                        title:{
                            display:true,
                            text:'Precision-Performance tradeoff - up and to the right is better'
                        },
                        scales: {
                            xAxes: [{
                                display: true,
                                type: 'linear',
                                max: '1',
                                position: 'bottom',
                                scaleLabel: {
                                    display: true,
                                    labelString: ' %(xlabel)s   '
                                }
                            }],
                            yAxes: [{
                                display: true,
                                type: 'logarithmic',
                                scaleLabel: {
                                    display: true,
                                    labelString: 'Queries per second - larger is better'
                                }
                            }]
                        }
                    }
                }); """ % { "xlabel" :  metric["description"]}

    output_str += """
        </script>
        """
    return output_str

def process_dataset(ds, runs, all_algos, queries, metric):
    all_data = {}

    for run in runs[ds]:
        algo = run["library"]
        algo_name = run["name"]
        build_time = run["build_time"]
        search_time = run["best_search_time"]
        results = zip(queries[ds], run["results"])

        precision = None
        print "--"
        print algo_name
        if metric == metrics["k-nn"] or metric == metrics["epsilon"]:
            total = 0
            actual = 0
            for (query, max_distance, closest), [time, candidates] in results:
                # Both these metrics actually use an epsilon, although k-nn
                # does so only because comparing floating-point numbers for
                # true equality is a terrible idea
                comparator = None
                if metric == metrics["k-nn"]:
                    epsilon = 1e-10
                    comparator = \
                        lambda (index, distance): \
                            distance <= (max_distance + epsilon)
                elif metric == metrics["epsilon"]:
                    epsilon = 0.01
                    comparator = \
                        lambda (index, distance): \
                            distance <= ((1 + epsilon) * max_distance)

                within = filter(comparator, candidates)
                if "brute" in algo_name.lower():
                    if len(within) != len(closest):
                        print "? what? brute-force strategy failed on ", \
                                closest, candidates
                total += len(closest)
                actual += len(within)
            print "total = ", total, ", actual = ", actual
            precision = float(actual) / float(total)
        elif metric == metrics["rel"]:
            total_closest_distance = 0.0
            total_candidate_distance = 0.0
            for (query, max_distance, closest), [time, candidates] in results:
                for (ridx, rdist), (cidx, cdist) in zip(closest, candidates):
                    total_closest_distance += rdist
                    total_candidate_distance += cdist
            precision = 0.0
            if total_closest_distance > 0.0001:
                precision = total_candidate_distance / total_closest_distance
        else:
            assert False, "precision metric '%s' is not supported" % metric["description"]
        print precision

        all_data.setdefault(algo, []).append((algo_name, float(build_time), float(search_time), float(precision)))
    return create_plot(ds, all_data, metric)



# Construct palette by reading all inputs
runs = {}
all_algos = set()
queries = {}

for ds in args.dataset:
    results_fn = get_fn("results", ds)
    queries_fn = get_fn("queries", ds)
    if not os.path.exists(queries_fn):
        assert False, "the queries file '%s' is missing" % queries_fn
    else:
        queries[ds] = pickle.load(open(queries_fn))
        runs[ds] = []
        for line in open(get_fn("results", ds)):
            run = json.loads(line)
            runs[ds].append(run)
            all_algos.add(run["library"])

# Build a website for each dataset
for ds in args.dataset:
    output_str = """
<html>
    <head>
        <title>%(id)s dataset</title>
        <script src="js/Chart.min.js"></script>
    </head>
    <body>
        <h2>Plots for %(id)s""" % { "id" : ds }
    for metric in args.precision:
        print "Processing '%s' with %s" % (ds, metrics[metric]["description"])
        output_str += process_dataset(ds, runs, all_algos, queries, metrics[metric])

    output_str += """
    </body>
</html>
"""
    with open(outputdir + ds + ".html", "w") as text_file:
        text_file.write(output_str)

# Build an index page
with open(outputdir + "index.html", "w") as text_file:
    output_str = """
<html>
    <head>
        <title>ANN-Benchmarks</title>
    </head>
    <body>
        <h2>Overview over Datasets</h2>
        <p>Click on a dataset to see the performance/quality plots.</p>
        <ul>"""
    for ds in args.dataset:
        output_str += """
            <li><a href="%(id)s.html">%(id)s</a></li>""" % { "id" : ds }
    output_str += """
        <ul>
    </body>
</html>"""
    text_file.write(output_str)

