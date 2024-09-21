## BESTIN 1.0

### Gateway 1.0 기본 버전
- 사진처럼 결선 
- `CTRL 485A, CTRL 485B`: 라인 A, B / `ENERGY 485A, ENERGY 485B`: 라인 A, B

![Gateway 1.0 기본](/images/gateway1.0_default.png)

### Gateway 1.0 구형 버전
- 사진상의 게이트웨이인 경우, **RS485B** 부분에 결선하세요.

![Gateway 1.0 구형](/images/gateway1.0_old.png)

### Gateway 1.0 일체형 버전
- 월패드 후면의 CTRL 랜선을 브릿지하여 브릿지한 랜선 중에서 흰주, 주, 흰파, 파를 EW11에 각각 연결하세요.

  환경에 따라 속선의 색상이나 랜선의 종류가 다를 수 있으니, 이에 유의해 작업을 진행하세요.
  다른 환경에 대한 제보는 환영입니다!

![Gateway 1.0 일체형](/images/gateway1.0_aio.png)

## BESTIN 2.0

### Gateway 2.0 기본 버전
- 사진처럼 포트가 나눠져 있는 경우, 에너지 컨트롤러 포트 1개와 미세먼지 포트 1개에 랜선을 연결하세요.

  랜선을 잘라서 흰파, 파 선을 EW11에 각각 연결하면 됩니다. `2번째 사진 참고`
  환경에 따라 속선의 색상이나 랜선의 종류가 다를 수 있으니, 작업 시 주의하세요.

![Gateway 2.0 기본](/images/gateway2.0_default.png)

![Gateway 2.0 기본 연결](/images/gateway2.0_default_connect.png)

### Gateway 2.0 신형 버전
- 1.3.3 버전부터 디밍 세대에 대한 지원을 시작합니다. 아직 모든 데이터가 완전히 분석되지 않았습니다.
  - 사진을 참고하여 디밍 세대인지 확인해 보세요.
  - 추가적인 패킷 데이터에 대한 제보를 기다립니다.
  - [디밍 테스트](/tests/dimming_test.py) 코드를 사용하여 좀 더 세부적으로 분석이 가능합니다.

![Gateway 2.0 디밍](/images/gateway2.0_dimming.png)

![Gateway 2.0 에너지 컨트롤러](/images/gateway2.0_energy_controller.png)
