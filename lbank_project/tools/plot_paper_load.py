"""Render the stage summaries and the million-account resource trace to PNG."""
import argparse
import csv
import io
import json
from pathlib import Path

import pypdfium2 as pdfium
from reportlab.graphics import renderPDF
from reportlab.graphics.charts.lineplots import LinePlot
from reportlab.graphics.shapes import Drawing
from reportlab.lib.colors import HexColor
from reportlab.pdfgen.canvas import Canvas


def label(canvas, x, y, value, size=10, color='#445466', bold=False):
    canvas.setFillColor(HexColor(color))
    canvas.setFont('Helvetica-Bold' if bold else 'Helvetica', size)
    canvas.drawString(x, y, str(value))


def panel(canvas, x, y, title, color, points, top, ticks, markers=False):
    width, height = 289, 126
    label(canvas, x, y+height+30, title, 14, '#182431', True)
    for index in range(5):
        level = top * index / 4
        yp = y + height * index / 4
        canvas.setStrokeColor(HexColor('#dbe2e8'))
        canvas.line(x, yp, x+width, yp)
        label(canvas, x-29, yp-3, f'{level:g}', 8)
    plot = LinePlot()
    plot.x, plot.y = 0, 0
    plot.width, plot.height = width, height
    plot.data = [points]
    plot.xValueAxis.valueMin, plot.xValueAxis.valueMax = ticks[0][0], ticks[-1][0]
    plot.yValueAxis.valueMin, plot.yValueAxis.valueMax = 0, top
    plot.xValueAxis.visible = plot.yValueAxis.visible = False
    plot.lines[0].strokeColor = HexColor(color)
    plot.lines[0].strokeWidth = 2
    drawing = Drawing(width, height)
    drawing.add(plot)
    renderPDF.draw(drawing, canvas, x, y)
    def project(value):
        return x + width * (value - ticks[0][0]) / (ticks[-1][0] - ticks[0][0])
    if markers:
        canvas.setFillColor(HexColor(color))
        for xp, yp in points:
            canvas.circle(project(xp), y+height*yp/top, 3, stroke=0, fill=1)
    for number, value in ticks:
        label(canvas, project(number)-5, y-15, value, 8)


def save_png(canvas, buffer, path):
    canvas.showPage()
    canvas.save()
    pdf = pdfium.PdfDocument(buffer.getvalue())
    page = pdf[0]
    page.render(scale=1.5).to_pil().save(path)
    page.close()
    pdf.close()


def disk_chart(trace, output):
    with trace.open() as stream:
        samples = list(csv.DictReader(stream))
    if not samples[0].get('device_busy_ms'):
        return
    series = [[], [], []]
    first = samples[0]
    end = float(samples[-1]['elapsed_s'])
    for sample in samples[1:]:
        start = float(first['elapsed_s'])
        elapsed = float(sample['elapsed_s']) - start
        if elapsed >= 5 or sample is samples[-1]:
            for points, key, divisor in zip(series, ('device_read_bytes', 'device_write_bytes', 'device_busy_ms'),
                                            (2**20, 2**20, 10)):
                delta = int(sample[key]) - int(first[key])
                points.append((start + elapsed / 2, delta / divisor / elapsed))
            first = sample
    buffer = io.BytesIO()
    canvas = Canvas(buffer, pagesize=(1070, 320))
    label(canvas, 42, 278, 'Avina  |  Disk activity during one million paper fills', 23, '#152331', True)
    label(canvas, 42, 252, 'Repeat run  /  Linux block counters for the virtual device holding the test database', 12)
    ticks = [(end*j/4, f'{end*j/4:.0f}s') for j in range(5)]
    for i, (points, name, color) in enumerate(zip(series, ('Reads  /  MiB per second',
            'Writes  /  MiB per second', 'Device busy  /  percent'), ('#136da1','#a75719','#087f6a'))):
        upper = 100 if i == 2 else 1
        while upper < max(y for _, y in points):
            upper *= 2
        panel(canvas, 56+351*i, 62, name, color, points, upper, ticks)
    label(canvas, 42, 18, '5-second mean rates. Device activity includes other Docker workloads and excludes data served by the OS page cache.', 10)
    save_png(canvas, buffer, output)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('report', type=Path)
    root = parser.parse_args().report
    stages = sorted((json.loads(p.read_text()) for p in root.glob('batched-replay-*.json')),
                    key=lambda v:v['users'])
    with (root/'batched-replay-1000000.csv').open() as stream:
        samples = [(float(v['elapsed_s']),float(v['cpu_seconds_since_start']),
                    int(v['container_memory_bytes'])/2**20,int(v['database_bytes'])/2**20)
                   for v in csv.DictReader(stream)]
    # Smooth only the CPU trace. Calculate a time-weighted average for each >= 5s window.
    anchor = samples[0]
    cpu = []
    for row in samples[1:]:
        dt = row[0] - anchor[0]
        if dt >= 5 or row is samples[-1]:
            cpu.append(((row[0]+anchor[0])/2,(row[1]-anchor[1])/dt))
            anchor = row
    traces = [cpu,[(v[0],v[2]) for v in samples],[(v[0],v[3]) for v in samples]]
    buffer = io.BytesIO()
    canvas = Canvas(buffer,pagesize=(1070,565))
    label(canvas, 42, 524, 'Avina  |  Paper execution under load', 24, '#152331', True)
    label(canvas, 42, 501, '4 workers  /  one funded test account per fill  /  fixed BTC quote  /  Docker Linux', 12)
    label(canvas, 42, 463, 'By account population', 16, '#152331', True)
    label(canvas, 42, 239, 'During the one-million-account run', 16, '#152331', True)
    keys = ['mean_cpu_cores','peak_memory_mib','peak_db_mib']
    titles = ['CPU  /  mean cores','RAM  /  peak MiB','Database files  /  peak MiB']
    time_titles = ['CPU  /  cores, 5s average','RAM  /  MiB including page cache','Database files  /  MiB']
    colors = ['#136da1','#087f6a','#a75719']
    end = samples[-1][0]
    for i in range(3):
        upper = [4,800,256][i]
        largest = max(max(v[keys[i]] for v in stages),max(v for _,v in traces[i]))
        while largest > upper:
            upper *= 1.25
        xpos = 56+351*i
        panel(canvas, xpos, 285, titles[i], colors[i],
              [(j,r[keys[i]]) for j,r in enumerate(stages)], upper,
              list(enumerate(['10','100','1k','10k','100k','1M'])),True)
        panel(canvas,xpos,63,time_titles[i],colors[i],traces[i],upper,
              [(end*j/4,f'{end*j/4:.0f}s') for j in range(5)])
    label(canvas,42,20,'CPU and RAM are container measurements. Disk is sampled DB/WAL file size across the four shards. Time includes seeding, execution, commit and readback.',10)
    save_png(canvas, buffer, root/'resource-usage.png')
    io_trace = root/'disk-io'/'batched-replay-1000000.csv'
    if io_trace.is_file():
        disk_chart(io_trace, root/'disk-activity.png')


if __name__ == '__main__':
    main()
