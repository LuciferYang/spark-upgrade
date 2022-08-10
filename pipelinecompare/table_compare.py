import argparse
from pyspark.sql import SparkSession

spark = SparkSession.builder.getOrCreate()

parser = argparse.ArgumentParser(
    description='Compare two different versions of a pipeline.' +
    'Either --tables and --control-root and --target-root or ' +
    '--control-tables and --target-tables must be specified.')
parser.add_argument('--tables', type=str, nargs='+', required=False,
                    help='Name of the tables.')
parser.add_argument('--format', type=str, help='Format of the table')
parser.add_argument('--control-root', type=str,
                    help='root directory for the control files')
parser.add_argument('--target-root', type=str,
                    help='root directory for the target files')
parser.add_argument('--control-tables', type=str,
                    nargs='+', help='control tables')
parser.add_argument('--target-tables', type=str,
                    nargs='+', help='target tables')
parser.add_argument('--compare-precision', type=int,
                   help='Precision for fractional comparisons.')
parser.add_argument('--row-diff-tolerance', type=float, default=0.0,
                   help='Tolerance for % of different rows')
args = parser.parse_args()

def compare_tables(control, target):
    if control.schema != target.schema:
        control.printSchema()
        target.printSchema()
        raise Exception("Control schema and target schema do not match")
    if parser.compare_precision is not None:
        columns = control.columns
        schema = control.schema
        if isinstance(schema[c].dataType, FractionalType):
            control = control.withColumn(c, round(control[c], parser.compare_precision))
            target = control.withColumn(c, round(target[c], parser.compare_precision))
    control.persist()
    target.persist()
    control_count = control.count()
    target_count = target.count()
    # Do diffs on the data, but subtract doesn't support all data types so fall back to strings.
    try:
        missing_rows = control.subtract(target)
        new_rows = target.subtract(control)
    except Exception as e:
        # TODO: only convert the columns that need to be converted.
        print(f"Warning converting all to strings.... {e}")
        columns = control.columns
        for c in columns:
            control = control.withColumn(c, control[c].cast('string'))
            target = target.withColumn(c, target[c].cast('string'))
        missing_rows = control.subtract(target)
        new_rows = target.subtract(control)
    new_rows_count = new_rows.count()
    if new_rows_count > 0:
        print(f"Found {new_rows_count} that were not in the control")
        new_rows.show()
    missing_rows_count = missing_rows.count()
    if missing_rows_count > 0:
        print(f"Found {missing_rows_count} missing from new new pipeline")
        missing_rows.show()
    changed_rows = new_rows_count + missing_rows_count
    row_diff_tol = args.row_diff_tolerance
    if changed_rows >  row_diff_tol * control_count:
        raise Exception(f"Data differs in table by more than {100 * row_diff_tol}%, failing.")

    if control_count != target_count:
        print(f"Counts do not match! {control_count} {target_count}")
        try:
            # Handle duplicates, will fail on maps.
            counted_control = control.groupBy(
                *control.columns).count().persist()
            counted_target = target.groupBy(*target.columns).count().persist()
            new_rows = counted_target.subtract(counted_control)
            missing_rows = counted_control.subtract(counted_target)
            new_rows_count = new_rows.count()
            if new_rows_count > 0:
                print(f"Found {new_rows_count} that were not in the control")
                new_rows.show()
            missing_rows_count = missing_rows.count()
            if missing_rows_count > 0:
                print(
                    f"Found {missing_rows_count} missing from new new pipeline")
                missing_rows.show()
        except Exception as e:
            raise Exception(f"Data counts differ but {e} prevents grouping cmp")


if args.control_root is not None:
    for table in args.tables:
        control = spark.read.format(args.format).load(
            f"{args.control_root}/{table}")
        target = spark.read.format(args.format).load(
            f"{args.target_root}/{table}")
        compare_tables(control, target)
else:
    tables = zip(args.control_tables, args.target_tables)
    for (ctrl_name, target_name) in tables:
        compare_tables(spark.read.table(ctrl_name),
                       spark.read.table(target_name))
