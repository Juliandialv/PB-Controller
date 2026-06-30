from src.bench.bench_controller import  BenchController

bench = BenchController()

try:
    bench.home_axis()
    bench.go_to(90.5,130)

finally:
    bench.close()
